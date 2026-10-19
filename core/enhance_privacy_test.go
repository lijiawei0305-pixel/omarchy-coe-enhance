package app

import (
	"os"
	"strings"
	"testing"
)

func TestPipelineResultDoesNotLogBody(t *testing.T) {
	data, err := os.ReadFile("runtime.go")
	if err != nil {
		t.Fatal(err)
	}
	for _, forbidden := range []string{`"transcript", processed.Transcript`, `"corrected", processed.Corrected`} {
		if strings.Contains(string(data), forbidden) {
			t.Fatal("plaintext pipeline result logged")
		}
	}
}
