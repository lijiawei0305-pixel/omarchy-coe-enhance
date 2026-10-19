package perf

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestDisabledAndPrivateTrace(t *testing.T) {
	t.Setenv("COE_PERF_TRACE", "")
	if New() != nil {
		t.Fatal("default must be off")
	}
	dir := t.TempDir()
	path := filepath.Join(dir, "trace.jsonl")
	t.Setenv("COE_PERF_TRACE", path)
	tr := New()
	tr.Session("test-session")
	Mark(With(context.Background(), tr), "T0")
	data, err := os.ReadFile(path)
	if err != nil || !strings.Contains(string(data), `"event":"T0"`) {
		t.Fatal("missing event")
	}
	info, _ := os.Stat(path)
	if info.Mode().Perm() != 0600 {
		t.Fatal("unsafe mode")
	}
	link := filepath.Join(dir, "link")
	os.Symlink(path, link)
	t.Setenv("COE_PERF_TRACE", link)
	tr.Mark("forbidden")
	again, _ := os.ReadFile(path)
	if string(data) != string(again) {
		t.Fatal("followed symlink")
	}
	os.Chmod(path, 0644)
	t.Setenv("COE_PERF_TRACE", path)
	tr.Mark("forbidden")
	again, _ = os.ReadFile(path)
	if string(data) != string(again) {
		t.Fatal("wrote public file")
	}
}
