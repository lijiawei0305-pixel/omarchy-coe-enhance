package asr

import (
	"coe/internal/audio"
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestAliyunNeverEchoesRemoteBody(t *testing.T) {
	for _, body := range []string{`{"code":"Error","message":"PRIVATE-KEY TRANSCRIPT"}`, `invalid PRIVATE-KEY TRANSCRIPT`} {
		for _, status := range []int{200, 401, 429, 500} {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(status); _, _ = w.Write([]byte(body)) }))
			c := AliyunASRClient{Endpoint: server.URL, Model: "qwen-audio-3.0-asr-flash", APIKey: "key"}
			_, err := c.Transcribe(context.Background(), audio.Result{Data: make([]byte, 320), ByteCount: 320, SampleRate: 16000, Channels: 1, Format: "s16"})
			server.Close()
			if err == nil || strings.Contains(err.Error(), "PRIVATE") || strings.Contains(err.Error(), "TRANSCRIPT") {
				t.Fatalf("unsafe remote error: %v", err)
			}
		}
	}
}
