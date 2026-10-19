// Package perf writes opt-in, bounded, credential-free diagnostic events.
package perf

import (
	"context"
	"crypto/rand"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"golang.org/x/sys/unix"
	"net/http/httptrace"
	"os"
	"sync"
	"time"
)

type key struct{}
type Trace struct {
	mu          sync.Mutex
	id, session string
	start       time.Time
}

var writerMu sync.Mutex

func New() *Trace {
	if os.Getenv("COE_PERF_TRACE") == "" {
		return nil
	}
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return nil
	}
	return &Trace{id: hex.EncodeToString(b[:]), start: time.Now()}
}
func With(ctx context.Context, t *Trace) context.Context {
	if t == nil {
		return ctx
	}
	return context.WithValue(ctx, key{}, t)
}
func From(ctx context.Context) *Trace { t, _ := ctx.Value(key{}).(*Trace); return t }
func (t *Trace) Session(id string) {
	if t == nil {
		return
	}
	t.mu.Lock()
	t.session = id
	t.mu.Unlock()
}
func Mark(ctx context.Context, event string) { From(ctx).Mark(event) }
func (t *Trace) Mark(event string)           { t.emit(event, nil) }
func (t *Trace) emit(event string, fields map[string]any) {
	if t == nil {
		return
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	var ts unix.Timespec
	_ = unix.ClockGettime(unix.CLOCK_MONOTONIC, &ts)
	row := map[string]any{"component": "coe", "trace_id": t.id, "session_id": t.session, "event": event, "elapsed_ms": float64(time.Since(t.start)) / float64(time.Millisecond), "monotonic_ns": ts.Nano()}
	for k, v := range fields {
		row[k] = v
	}
	data, err := json.Marshal(row)
	if err != nil {
		return
	}
	writerMu.Lock()
	defer writerMu.Unlock()
	// Never follow links, loosen permissions, or append to someone else's file.
	fd, err := unix.Open(os.Getenv("COE_PERF_TRACE"), unix.O_APPEND|unix.O_CREAT|unix.O_WRONLY|unix.O_NOFOLLOW|unix.O_CLOEXEC|unix.O_NONBLOCK, 0600)
	if err != nil {
		return
	}
	f := os.NewFile(uintptr(fd), "perf")
	defer f.Close()
	var st unix.Stat_t
	if unix.Fstat(fd, &st) != nil || st.Uid != uint32(os.Getuid()) || st.Mode&0777 != 0600 || st.Mode&unix.S_IFMT != unix.S_IFREG || st.Nlink != 1 || st.Size+int64(len(data))+1 > 10*1024*1024 {
		return
	}
	_, _ = f.Write(append(data, '\n'))
}

// HTTP traces metadata only: never host, URL, request/response headers or body.
func HTTP(ctx context.Context, stage string) context.Context {
	t := From(ctx)
	if t == nil {
		return ctx
	}
	return httptrace.WithClientTrace(ctx, &httptrace.ClientTrace{
		GetConn:  func(string) { t.Mark(stage + "_get_conn") },
		GotConn:  func(i httptrace.GotConnInfo) { t.emit(stage+"_connection", map[string]any{"reused": i.Reused}) },
		DNSStart: func(httptrace.DNSStartInfo) { t.Mark(stage + "_dns_start") }, DNSDone: func(httptrace.DNSDoneInfo) { t.Mark(stage + "_dns_done") },
		ConnectStart: func(string, string) { t.Mark(stage + "_tcp_start") }, ConnectDone: func(string, string, error) { t.Mark(stage + "_tcp_done") },
		TLSHandshakeStart: func() { t.Mark(stage + "_tls_start") }, TLSHandshakeDone: func(tls.ConnectionState, error) { t.Mark(stage + "_tls_done") },
		WroteRequest: func(httptrace.WroteRequestInfo) { t.Mark(stage + "_upload_done") }, GotFirstResponseByte: func() { t.Mark(stage + "_first_byte") },
	})
}
