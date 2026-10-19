// DashScope native non-streaming ASR. Kept separate from OpenAI/vLLM adapters.
package asr

import (
	"bytes"
	"coe/internal/audio"
	"coe/internal/perf"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type AliyunASRClient struct {
	Endpoint, Model, APIKey, APIKeyEnv, Language, Prompt string
	HTTPClient                                           *http.Client
}

func (c AliyunASRClient) Name() string { return "aliyun-asr-" + c.Model }
func (c AliyunASRClient) Transcribe(ctx context.Context, capture audio.Result) (Result, error) {
	key, _, err := resolveRequiredAPIKey("aliyun", c.APIKey, c.APIKeyEnv, "DASHSCOPE_API_KEY")
	if err != nil {
		return Result{}, err
	}
	if strings.TrimSpace(c.Endpoint) == "" || strings.TrimSpace(c.Model) == "" {
		return Result{}, fmt.Errorf("aliyun ASR requires endpoint and model")
	}
	wav, err := audio.EncodeWAV(capture)
	if err != nil {
		return Result{}, err
	}
	// The documented Data URI input limit is 10 MB, including Base64 overhead.
	if base64.StdEncoding.EncodedLen(len(wav)) > 10*1024*1024-64 {
		return Result{}, fmt.Errorf("aliyun ASR audio exceeds 10 MB encoded limit")
	}
	messages := []any{}
	if p := strings.TrimSpace(c.Prompt); p != "" {
		if len([]rune(p)) > 400 {
			return Result{}, fmt.Errorf("aliyun ASR context exceeds 400 characters")
		}
		messages = append(messages, map[string]any{"role": "user", "content": []any{map[string]any{"type": "input_text", "text": p}}})
	}
	messages = append(messages, map[string]any{"role": "user", "content": []any{map[string]any{"type": "input_audio", "input_audio": map[string]any{"data": "data:audio/wav;base64," + base64.StdEncoding.EncodeToString(wav)}}}})
	params := map[string]any{"format": "wav", "sample_rate": strconv.Itoa(capture.SampleRate)}
	if lang := strings.TrimSpace(c.Language); lang != "" && lang != "auto" {
		hints := strings.Split(lang, ",")
		if len(hints) > 4 {
			return Result{}, fmt.Errorf("aliyun ASR accepts at most four language hints")
		}
		for i := range hints {
			hints[i] = strings.TrimSpace(hints[i])
		}
		params["language_hints"] = hints
	}
	payload := map[string]any{"model": c.Model, "input": map[string]any{"messages": messages}, "parameters": params}
	body, err := json.Marshal(payload)
	if err != nil {
		return Result{}, err
	}
	perf.Mark(ctx, "T2")
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.Endpoint, bytes.NewReader(body))
	if err != nil {
		return Result{}, err
	}
	req.Header.Set("Authorization", "Bearer "+key)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-DashScope-SSE", "disable")
	client := c.HTTPClient
	if client == nil {
		client = &http.Client{Timeout: 60 * time.Second}
	}
	perf.Mark(ctx, "T3")
	resp, err := client.Do(req)
	if err != nil {
		return Result{}, err
	}
	defer resp.Body.Close()
	// Do not echo remote response/error bodies: they can contain keys or transcripts.
	if resp.StatusCode >= 300 {
		return Result{}, fmt.Errorf("aliyun ASR HTTP %d", resp.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, 2*1024*1024+1))
	if err != nil {
		return Result{}, err
	}
	if len(data) > 2*1024*1024 {
		return Result{}, fmt.Errorf("aliyun ASR response too large")
	}
	var result struct {
		Code   string `json:"code"`
		Output struct {
			Text string `json:"text"`
		} `json:"output"`
	}
	if err = json.Unmarshal(data, &result); err != nil {
		return Result{}, fmt.Errorf("aliyun ASR invalid JSON response")
	}
	if result.Code != "" {
		return Result{}, fmt.Errorf("aliyun ASR provider rejected request")
	}
	text := strings.TrimSpace(result.Output.Text)
	if text == "" {
		return Result{Warning: "aliyun ASR returned empty text"}, nil
	}
	return Result{Text: text}, nil
}
