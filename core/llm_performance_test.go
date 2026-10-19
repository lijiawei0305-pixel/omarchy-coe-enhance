package llm

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestChatDoesNotRetryBillableErrors(t *testing.T) {
	for _, code := range []int{401, 429, 500} {
		t.Run(http.StatusText(code), func(t *testing.T) {
			var calls atomic.Int64
			s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				io.Copy(io.Discard, r.Body)
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(code)
				io.WriteString(w, `{"error":{"message":"private-transcript-and-key"}}`)
			}))
			defer s.Close()
			c := OpenAICorrector{Endpoint: s.URL + "/v1", EndpointType: "chat", APIKey: "mock", ResolvedPrompt: "保留 VASP 和 DFT", Timeout: time.Second, HTTPClient: s.Client()}
			_, err := c.Correct(context.Background(), "私密正文")
			if err == nil || calls.Load() != 1 || strings.Contains(err.Error(), "private-") {
				t.Fatalf("unsafe or retried: calls=%d", calls.Load())
			}
		})
	}
}
func TestChatUsesConfiguredHTTPClient(t *testing.T) {
	var calls atomic.Int64
	c := OpenAICorrector{Endpoint: "https://unused.invalid/v1", EndpointType: "chat", APIKey: "mock", Model: "qwen-mock", ResolvedPrompt: "dictionary preserved", HTTPClient: &http.Client{Transport: perfRoundTrip(func(r *http.Request) (*http.Response, error) {
		calls.Add(1)
		var p map[string]any
		if json.NewDecoder(r.Body).Decode(&p) != nil || p["max_tokens"] != float64(300) || p["model"] != "qwen-mock" {
			t.Error("request parameters changed")
		}
		return &http.Response{StatusCode: 200, Header: http.Header{"Content-Type": []string{"application/json"}}, Body: io.NopCloser(strings.NewReader(`{"choices":[{"message":{"content":"中文 Cu(111)"}}]}`))}, nil
	})}}
	out, err := c.Correct(context.Background(), "text")
	if err != nil || out.Text != "中文 Cu(111)" || calls.Load() != 1 {
		t.Fatalf("configured client: calls=%d err=%v textMatches=%v", calls.Load(), err, out.Text == "中文 Cu(111)")
	}
}

type perfRoundTrip func(*http.Request) (*http.Response, error)

func (f perfRoundTrip) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestChatCancelsInflightRequest(t *testing.T) {
	entered := make(chan struct{})
	exited := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.Copy(io.Discard, r.Body)
		close(entered)
		<-r.Context().Done()
		close(exited)
	}))
	defer server.Close()
	c := OpenAICorrector{Endpoint: server.URL + "/v1", EndpointType: "chat", APIKey: "mock", ResolvedPrompt: "保留术语", HTTPClient: server.Client()}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { _, err := c.Correct(ctx, "私密文本"); done <- err }()
	select {
	case <-entered:
	case <-time.After(time.Second):
		t.Fatal("request not started")
	}
	cancel()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("ignored cancellation")
		}
	case <-time.After(time.Second):
		t.Fatal("request did not cancel")
	}
	select {
	case <-exited:
	case <-time.After(time.Second):
		t.Fatal("HTTP request still running")
	}
}
