// Built inside pinned Coe source so tests use the real internal/asr Adapters.
package main

import (
	"coe/internal/asr"
	"coe/internal/audio"
	"coe/internal/config"
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"time"
)

func main() {
	var req struct {
		Profile struct {
			Provider string `json:"provider"`
			Endpoint string `json:"endpoint"`
			Model    string `json:"model"`
			Language string `json:"language"`
			Prompt   string `json:"prompt"`
			Timeout  int    `json:"timeout"`
			KeyRef   string `json:"key_ref"`
		} `json:"profile"`
		APIKey string `json:"api_key"`
	}
	if err := json.NewDecoder(os.Stdin).Decode(&req); err != nil {
		fail(err)
	}
	_ = config.LoadEnvFile()
	p := req.Profile
	cfg := config.ASRConfig{Provider: p.Provider, Endpoint: p.Endpoint, Model: p.Model, Language: p.Language, Prompt: p.Prompt, TimeoutSeconds: p.Timeout, APIKey: req.APIKey, APIKeyEnv: p.KeyRef}
	client, err := asr.NewClient(cfg)
	if err != nil {
		fail(err)
	}
	pcm := make([]byte, 16000)
	for i := 0; i < len(pcm)/2; i++ {
		binary.LittleEndian.PutUint16(pcm[i*2:], uint16(int16(3000*math.Sin(float64(i)*2*math.Pi*440/16000))))
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(max(1, p.Timeout))*time.Second)
	defer cancel()
	result, err := client.Transcribe(ctx, audio.Result{Data: pcm, ByteCount: len(pcm), SampleRate: 16000, Channels: 1, Format: "s16"})
	if err != nil {
		fail(err)
	}
	if result.Text == "" {
		fail(fmt.Errorf("empty text"))
	}
	fmt.Printf("{\"ok\":true,\"characters\":%d}\n", len([]rune(result.Text)))
}
func fail(err error) { fmt.Fprintln(os.Stderr, err); os.Exit(1) }
