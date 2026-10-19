package audio

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestEnhanceRecorderRequestsRawPCM(t *testing.T) {
	binary := filepath.Join(t.TempDir(), "recorder")
	script := "#!/bin/sh\ncase \" $* \" in *' --raw '*) ;; *) exit 17;; esac\nprintf '\\001\\000\\002\\000'\nexec sleep 20\n"
	if err := os.WriteFile(binary, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	recorder := PWRecord{Binary: binary, SampleRate: 16000, Channels: 1, Format: "s16"}
	session, err := recorder.Start(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	time.Sleep(50 * time.Millisecond)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	result, err := session.Stop(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if string(result.Data) != string([]byte{1, 0, 2, 0}) {
		t.Fatalf("expected raw PCM; got %v", result.Data)
	}
}
