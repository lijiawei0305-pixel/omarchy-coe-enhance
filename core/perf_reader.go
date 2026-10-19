package audio

import (
	"coe/internal/perf"
	"io"
)

type firstPCMReader struct {
	io.Reader
	trace *perf.Trace
	seen  bool
}

func (r *firstPCMReader) Read(p []byte) (int, error) {
	n, e := r.Reader.Read(p)
	if n > 0 && !r.seen {
		r.trace.Mark("first_pcm")
		r.seen = true
	}
	return n, e
}
