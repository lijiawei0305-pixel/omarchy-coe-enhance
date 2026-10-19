package audio

import (
	"bytes"
	"context"
	"encoding/binary"
	"io"
	"math"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"testing"
	"time"
)

func levelPCM(value int16, n int) []byte {
	p := make([]byte, n*2)
	for i := 0; i < n; i++ {
		binary.NativeEndian.PutUint16(p[i*2:], uint16(value))
	}
	return p
}
func testHub(t *testing.T) *levelHub {
	t.Helper()
	h, e := newLevelHub(filepath.Join(t.TempDir(), "levels/audio.sock"))
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(h.close)
	return h
}
func levelClient(t *testing.T, h *levelHub) *net.UnixConn {
	t.Helper()
	c, e := net.DialUnix("unix", nil, h.listener.Addr().(*net.UnixAddr))
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { c.Close() })
	deadline := time.Now().Add(time.Second)
	for h.count.Load() == 0 {
		if time.Now().After(deadline) {
			t.Fatal("accept timeout")
		}
		runtime.Gosched()
	}
	return c
}
func TestLevelsRealPCMNativeFrameAndSilence(t *testing.T) {
	h := testHub(t)
	c := levelClient(t, h)
	tap := &levelTap{hub: h}
	p := append(levelPCM(-16384, 80), levelPCM(8192, 80)...)
	tap.push(p[:1])
	tap.push(p[1:83])
	tap.push(p[83:])
	tap.push(levelPCM(0, 160))
	c.SetReadDeadline(time.Now().Add(time.Second))
	var b [32]byte
	if _, e := io.ReadFull(c, b[:]); e != nil {
		t.Fatal(e)
	}
	f := func(off int) float32 { return math.Float32frombits(binary.NativeEndian.Uint32(b[off:])) }
	if binary.NativeEndian.Uint32(b[:4]) != 0 || f(4) != -.5 || f(8) != .25 || math.Abs(float64(f(12))+6.0206) > .001 {
		t.Fatalf("wrong native frame: %v", b[:16])
	}
	if binary.NativeEndian.Uint32(b[16:20]) != 1 || f(20) != 0 || f(24) != 0 || f(28) != -120 {
		t.Fatal("silence not -120dBFS")
	}
}
func TestLevelsSlowConsumerNeverBlocksPCM(t *testing.T) {
	h := testHub(t)
	c := levelClient(t, h)
	c.SetReadBuffer(128)
	tap := &levelTap{hub: h}
	p := levelPCM(10000, 16000*30)
	start := time.Now()
	tap.push(p)
	if time.Since(start) > 500*time.Millisecond {
		t.Fatal("slow OSD blocked PCM")
	}
	if len(h.frames) > 32 {
		t.Fatal("unbounded queue")
	}
}
func TestLevelsReaderPreservesPCM(t *testing.T) {
	h := testHub(t)
	levelClient(t, h)
	src := append(levelPCM(-32768, 160), levelPCM(32767, 160)...)
	reader := recordingLevelReader(context.WithValue(context.Background(), levelsKey{}, h), io.NopCloser(bytes.NewReader(src)), 16000, 1, "s16")
	dst, e := io.ReadAll(reader)
	if e != nil || !bytes.Equal(src, dst) {
		t.Fatal("PCM was modified")
	}
}
func TestLevelsUnsupportedFormatAndDisabled(t *testing.T) {
	h := testHub(t)
	ctx := context.WithValue(context.Background(), levelsKey{}, h)
	for _, v := range []struct {
		rate, ch int
		format   string
	}{{48000, 1, "s16"}, {16000, 2, "s16"}, {16000, 1, "f32"}} {
		if newLevelTap(ctx, v.rate, v.ch, v.format) != nil {
			t.Fatal("unsupported PCM was interpreted")
		}
	}
	t.Setenv("COE_ENHANCE_OSD", "0")
	_, close := WithRecordingLevels(ctx)
	close()
}
func TestLevelsSocketPrivacyCollisionAndCleanup(t *testing.T) {
	h := testHub(t)
	path := h.listener.Addr().String()
	st, e := os.Stat(path)
	if e != nil || st.Mode().Perm() != 0600 {
		t.Fatal("socket permissions")
	}
	if other, e := newLevelHub(path); e == nil {
		other.close()
		t.Fatal("stole listener")
	}
	c := levelClient(t, h)
	h.close()
	h.close()
	if _, e = os.Stat(path); !os.IsNotExist(e) {
		t.Fatal("socket not cleaned")
	}
	c.SetReadDeadline(time.Now().Add(time.Second))
	if _, e = c.Read(make([]byte, 16)); e != io.EOF {
		t.Fatalf("client not closed: %v", e)
	}
}
func TestLevelsRefuseUnrelatedFile(t *testing.T) {
	d := t.TempDir()
	p := filepath.Join(d, "audio.sock")
	os.WriteFile(p, []byte("keep"), 0600)
	if h, e := newLevelHub(p); e == nil {
		h.close()
		t.Fatal("overwrote unrelated file")
	}
	b, _ := os.ReadFile(p)
	if string(b) != "keep" {
		t.Fatal("data changed")
	}
}
func TestLevelsThirtySessionsReleaseResources(t *testing.T) {
	before := runtime.NumGoroutine()
	for i := 0; i < 30; i++ {
		h := testHub(t)
		c := levelClient(t, h)
		tap := &levelTap{hub: h}
		tap.push(levelPCM(500, 160))
		c.SetReadDeadline(time.Now().Add(time.Second))
		io.ReadFull(c, make([]byte, 16))
		h.close()
	}
	if n := runtime.NumGoroutine(); n > before+2 {
		t.Fatalf("goroutines %d -> %d", before, n)
	}
}
func BenchmarkRecordingLevels(b *testing.B) {
	h := &levelHub{frames: make(chan [16]byte, 32), done: make(chan struct{})}
	h.count.Store(1)
	p := levelPCM(1000, 16000)
	b.ReportAllocs()
	b.SetBytes(int64(len(p)))
	for i := 0; i < b.N; i++ {
		tap := &levelTap{hub: h}
		tap.push(p)
	}
}

func TestLevelsIdleClientsReapedWithoutFrames(t *testing.T) {
	h := testHub(t)
	for i := 0; i < 10; i++ {
		c := levelClient(t, h)
		c.Close()
		end := time.Now().Add(time.Second)
		for h.count.Load() != 0 {
			if time.Now().After(end) {
				t.Fatal("idle client leaked")
			}
			runtime.Gosched()
		}
	}
}
