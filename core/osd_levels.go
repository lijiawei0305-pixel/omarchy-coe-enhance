package audio

// AudioFrame wire adapter for the unmodified Voxtype 1.1.1 GTK4 OSD.
// No PCM leaves this process: the bounded channel holds only 16-byte levels.
import (
	"context"
	"encoding/binary"
	"io"
	"math"
	"net"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

type levelsKey struct{}
type levelHub struct {
	listener *net.UnixListener
	lock     *os.File
	frames   chan [16]byte
	done     chan struct{}
	mu       sync.Mutex
	clients  map[*net.UnixConn]bool
	count    atomic.Int32
	wg       sync.WaitGroup
	once     sync.Once
}

// WithRecordingLevels is opt-in for the Enhance integration. Failure is visual
// only. Closing the daemon context releases all clients, listener and lock.
func WithRecordingLevels(ctx context.Context) (context.Context, func()) {
	if os.Getenv("COE_ENHANCE_BRIDGE") != "1" || os.Getenv("COE_ENHANCE_OSD") == "0" {
		return ctx, func() {}
	}
	path := os.Getenv("COE_ENHANCE_OSD_SOCKET")
	if path == "" {
		if base := os.Getenv("XDG_RUNTIME_DIR"); base != "" {
			path = filepath.Join(base, "coe-enhance/osd/audio.sock")
		}
	}
	if path == "" {
		return ctx, func() {}
	}
	h, err := newLevelHub(path)
	if err != nil {
		return ctx, func() {}
	}
	return context.WithValue(ctx, levelsKey{}, h), h.close
}

func newLevelHub(path string) (*levelHub, error) {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, err
	}
	st, err := os.Lstat(dir)
	if err != nil {
		return nil, err
	}
	if !st.IsDir() || st.Mode().Perm()&0077 != 0 || st.Sys().(*syscall.Stat_t).Uid != uint32(os.Getuid()) {
		return nil, os.ErrPermission
	}
	fd, err := syscall.Open(filepath.Join(dir, "audio.lock"), syscall.O_CREAT|syscall.O_RDWR|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0600)
	if err != nil {
		return nil, err
	}
	lock := os.NewFile(uintptr(fd), "levels-lock")
	if err = syscall.Flock(fd, syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		lock.Close()
		return nil, err
	}
	if st, e := os.Lstat(path); e == nil {
		if st.Mode()&os.ModeSocket == 0 || st.Sys().(*syscall.Stat_t).Uid != uint32(os.Getuid()) {
			lock.Close()
			return nil, os.ErrPermission
		}
		if err = os.Remove(path); err != nil {
			lock.Close()
			return nil, err
		}
	} else if !os.IsNotExist(e) {
		lock.Close()
		return nil, e
	}
	l, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		lock.Close()
		return nil, err
	}
	if err = os.Chmod(path, 0600); err != nil {
		l.Close()
		lock.Close()
		return nil, err
	}
	h := &levelHub{listener: l, lock: lock, frames: make(chan [16]byte, 32), done: make(chan struct{}), clients: map[*net.UnixConn]bool{}}
	h.wg.Add(2)
	go h.accept()
	go h.broadcast()
	return h, nil
}
func (h *levelHub) accept() {
	defer h.wg.Done()
	for {
		c, err := h.listener.AcceptUnix()
		if err != nil {
			return
		}
		h.mu.Lock()
		select {
		case <-h.done:
			c.Close()
		default:
			if len(h.clients) >= 4 {
				c.Close()
			} else {
				h.clients[c] = true
				h.count.Add(1)
				h.wg.Add(1)
				go h.watch(c)
			}
		}
		h.mu.Unlock()
	}
}

// The frontend never sends data. Blocking on EOF reaps idle disconnected
// clients immediately, so repeated Shell reloads cannot fill the client limit.
func (h *levelHub) watch(c *net.UnixConn) {
	defer h.wg.Done()
	var b [1]byte
	_, _ = c.Read(b[:])
	h.mu.Lock()
	if h.clients[c] {
		delete(h.clients, c)
		h.count.Add(-1)
	}
	c.Close()
	h.mu.Unlock()
}
func (h *levelHub) broadcast() {
	defer h.wg.Done()
	for {
		select {
		case <-h.done:
			return
		case f := <-h.frames:
			h.mu.Lock()
			for c := range h.clients {
				c.SetWriteDeadline(time.Now().Add(5 * time.Millisecond))
				n, e := c.Write(f[:])
				if e != nil || n != len(f) {
					c.Close()
					delete(h.clients, c)
					h.count.Add(-1)
				}
			}
			h.mu.Unlock()
		}
	}
}
func (h *levelHub) close() {
	h.once.Do(func() {
		close(h.done)
		h.listener.Close()
		h.mu.Lock()
		for c := range h.clients {
			c.Close()
			delete(h.clients, c)
		}
		h.count.Store(0)
		h.mu.Unlock()
		h.wg.Wait()
		h.lock.Close()
	})
}
func (h *levelHub) publish(f [16]byte) {
	select {
	case <-h.done:
		return
	default:
	}
	select {
	case h.frames <- f:
	default:
	} // A slow/absent renderer never stalls PCM.
}

type levelTap struct {
	hub      *levelHub
	seq      uint32
	n        int
	min, max int16
	odd      bool
	low      byte
}

func newLevelTap(ctx context.Context, rate, channels int, format string) *levelTap {
	h, _ := ctx.Value(levelsKey{}).(*levelHub)
	if h == nil || rate != 16000 || channels != 1 || format != "s16" {
		return nil
	}
	return &levelTap{hub: h}
}
func (t *levelTap) push(p []byte) {
	if t == nil {
		return
	}
	// No consumer: retain byte parity only, do no sample/level calculations.
	if t.hub.count.Load() == 0 {
		t.n = 0
		if (len(p)+boolInt(t.odd))%2 != 0 && len(p) > 0 {
			t.low = p[len(p)-1]
			t.odd = true
		} else if len(p) > 0 {
			t.odd = false
		}
		return
	}
	for _, b := range p {
		if !t.odd {
			t.low = b
			t.odd = true
			continue
		}
		var pair [2]byte
		pair[0] = t.low
		pair[1] = b
		v := int16(binary.NativeEndian.Uint16(pair[:]))
		t.odd = false
		if t.n == 0 || v < t.min {
			t.min = v
		}
		if t.n == 0 || v > t.max {
			t.max = v
		}
		t.n++
		if t.n == 160 {
			lo, hi := float32(t.min)/32768, float32(t.max)/32768
			peak := math.Max(math.Abs(float64(lo)), math.Abs(float64(hi)))
			db := -120.0
			if peak > 0 {
				db = math.Max(-120, 20*math.Log10(peak))
			}
			var f [16]byte
			binary.NativeEndian.PutUint32(f[0:4], t.seq)
			binary.NativeEndian.PutUint32(f[4:8], math.Float32bits(lo))
			binary.NativeEndian.PutUint32(f[8:12], math.Float32bits(hi))
			binary.NativeEndian.PutUint32(f[12:16], math.Float32bits(float32(db)))
			t.hub.publish(f)
			t.seq++
			t.n = 0
		}
	}
}
func boolInt(b bool) int {
	if b {
		return 1
	}
	return 0
}

// Wrap the same pw-record stdout. Neither a second capture nor an audio copy.
type recordingLevelsReader struct {
	io.ReadCloser
	tap *levelTap
}

func (r *recordingLevelsReader) Read(p []byte) (int, error) {
	n, e := r.ReadCloser.Read(p)
	r.tap.push(p[:n])
	return n, e
}
func recordingLevelReader(ctx context.Context, r io.ReadCloser, rate, channels int, format string) io.ReadCloser {
	tap := newLevelTap(ctx, rate, channels, format)
	if tap == nil {
		return r
	}
	return &recordingLevelsReader{ReadCloser: r, tap: tap}
}
