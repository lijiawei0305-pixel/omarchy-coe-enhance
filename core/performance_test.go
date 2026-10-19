package pipeline

import (
	"coe/internal/asr"
	"coe/internal/audio"
	"coe/internal/config"
	"coe/internal/llm"
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"runtime"
	"sync/atomic"
	"testing"
	"time"
)

func fixture(seconds int) audio.Result {
	data := make([]byte, seconds*32000)
	for i := 0; i < len(data)/2; i++ {
		binary.LittleEndian.PutUint16(data[i*2:], uint16(int16(5000*math.Sin(float64(i)*2*math.Pi*400/16000))))
	}
	return audio.Result{Data: data, ByteCount: len(data), SampleRate: 16000, Channels: 1, Format: "s16"}
}
func BenchmarkActivity(b *testing.B) {
	for _, n := range []int{1, 10, 60} {
		b.Run(fmt.Sprint(n), func(b *testing.B) {
			r := fixture(n)
			b.ReportAllocs()
			b.ResetTimer()
			for b.Loop() {
				audio.AnalyzeActivity(r, audio.DefaultActivityThresholds())
			}
		})
	}
}
func BenchmarkAliyunPrepare(b *testing.B) {
	for _, n := range []int{1, 10, 60} {
		b.Run(fmt.Sprint(n), func(b *testing.B) {
			r := fixture(n)
			c := asr.AliyunASRClient{Endpoint: "http://mock/api", Model: "mock", APIKey: "mock", HTTPClient: &http.Client{Transport: roundTrip(func(r *http.Request) (*http.Response, error) {
				_, _ = io.Copy(io.Discard, r.Body)
				return &http.Response{StatusCode: 200, Body: io.NopCloser(&responseReader{}), Header: make(http.Header)}, nil
			})}}
			b.ReportAllocs()
			b.ResetTimer()
			for b.Loop() {
				if _, err := c.Transcribe(context.Background(), r); err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}

type responseReader struct{ done bool }

func (r *responseReader) Read(p []byte) (int, error) {
	if r.done {
		return 0, io.EOF
	}
	r.done = true
	return copy(p, `{"output":{"text":"ok"}}`), io.EOF
}

type roundTrip func(*http.Request) (*http.Response, error)

func (f roundTrip) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func TestPerformanceHTTPAudit(t *testing.T) {
	if os.Getenv("COE_PERF_AUDIT") == "" {
		t.Skip("explicit local audit")
	}
	var calls, conns atomic.Int64
	status := atomic.Int64{}
	status.Store(200)
	server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		io.Copy(io.Discard, r.Body)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(int(status.Load()))
		if r.URL.Path == "/v1/chat/completions" {
			io.WriteString(w, `{"choices":[{"message":{"content":"使用 VASP 和 DFT 计算 Cu(111) 表面的结合能。"}}]}`)
		} else {
			io.WriteString(w, `{"output":{"text":"我正在使用 Omarchy。"}}`)
		}
	}))
	server.Config.ConnState = func(_ net.Conn, s http.ConnState) {
		if s == http.StateNew {
			conns.Add(1)
		}
	}
	server.Start()
	defer server.Close()
	c, err := asr.NewClient(config.ASRConfig{Provider: "aliyun-asr", Endpoint: server.URL + "/asr", Model: "mock", APIKey: "mock"})
	if err != nil {
		t.Fatal(err)
	}
	l, err := llm.NewCorrectorWithResolvedPrompt(config.LLMConfig{Provider: "openai", Endpoint: server.URL + "/v1", EndpointType: "chat", APIKey: "mock", TimeoutSeconds: 5}, "保留专业术语 {{.Dictionary}}")
	if err != nil {
		t.Fatal(err)
	}
	initial := runtime.NumGoroutine()
	var before, after runtime.MemStats
	runtime.GC()
	runtime.ReadMemStats(&before)
	for i := 0; i < 30; i++ {
		if _, e := c.Transcribe(context.Background(), fixture(1)); e != nil {
			t.Fatal(e)
		}
		if _, e := l.Correct(context.Background(), "mock"); e != nil {
			t.Fatal(e)
		}
	}
	warmCalls, warmConns := calls.Load(), conns.Load()
	status.Store(500)
	t0 := time.Now()
	_, err = l.Correct(context.Background(), "mock")
	failureMs := float64(time.Since(t0)) / float64(time.Millisecond)
	failedCalls := calls.Load() - warmCalls
	if err == nil {
		t.Fatal("expected failure")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	start := time.Now()
	_, err = c.Transcribe(ctx, fixture(1))
	cancelMs := float64(time.Since(start)) / float64(time.Millisecond)
	if err == nil {
		t.Fatal("expected cancelled")
	}
	server.CloseClientConnections()
	http.DefaultClient.CloseIdleConnections()
	time.Sleep(100 * time.Millisecond)
	runtime.GC()
	runtime.ReadMemStats(&after)
	result := map[string]any{"warm_requests": warmCalls, "warm_connections": warmConns, "llm_500_calls": failedCalls, "llm_500_ms": failureMs, "cancel_ms": cancelMs, "goroutines_before": initial, "goroutines_after": runtime.NumGoroutine(), "heap_before": before.HeapAlloc, "heap_after": after.HeapAlloc}
	data, _ := json.Marshal(result)
	if path := os.Getenv("COE_PERF_AUDIT"); path != "" {
		if err := os.WriteFile(path, append(data, '\n'), 0600); err != nil {
			t.Fatal(err)
		}
	}
}
