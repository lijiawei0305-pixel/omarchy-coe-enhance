package audio

import (
	"encoding/binary"
	"math/rand"
	"reflect"
	"testing"
)

func referenceAnalyzeActivity(result Result, thresholds ActivityThresholds) Activity {
	if result.Format != "s16" || result.Channels != 1 || len(result.Data) < 2 {
		return Activity{}
	}

	sampleCount := len(result.Data) / 2
	if sampleCount == 0 {
		return Activity{}
	}

	const fullScale = 32768.0
	var maxAbs float64
	var activeCount int
	var clippingCount int
	var zeroCrossings int
	var sum float64
	var sumSquares float64

	samples := make([]int32, 0, sampleCount)
	for i := 0; i+1 < len(result.Data); i += 2 {
		sample := int32(int16(binary.LittleEndian.Uint16(result.Data[i : i+2])))
		samples = append(samples, sample)
		sum += float64(sample)
	}
	mean := sum / float64(sampleCount)

	activeThreshold := thresholds.MinPeakNormalized
	if activeThreshold <= 0 {
		activeThreshold = 1 / fullScale
	}
	clipThreshold := 0.98
	prevSign := 0

	for _, sample := range samples {
		centeredSigned := (float64(sample) - mean) / fullScale
		centered := centeredSigned
		if centered < 0 {
			centered = -centered
		}
		if centered > maxAbs {
			maxAbs = centered
		}
		if centered >= activeThreshold {
			activeCount++
		}
		if centered >= clipThreshold {
			clippingCount++
		}
		sumSquares += centered * centered

		sign := 0
		switch {
		case centeredSigned > 0:
			sign = 1
		case centeredSigned < 0:
			sign = -1
		}
		if sign != 0 {
			if prevSign != 0 && sign != prevSign {
				zeroCrossings++
			}
			prevSign = sign
		}
	}

	peak := maxAbs
	rms := 0.0
	if sampleCount > 0 {
		rms = sqrt(sumSquares / float64(sampleCount))
	}
	activeRatio := float64(activeCount) / float64(sampleCount)

	return Activity{
		Supported:           true,
		DCOffsetNormalized:  mean / fullScale,
		PeakNormalized:      peak,
		RMSNormalized:       rms,
		ActiveSampleRatio:   activeRatio,
		ClippingSampleRatio: float64(clippingCount) / float64(sampleCount),
		ZeroCrossingRate:    float64(zeroCrossings) / float64(sampleCount),
		ApproxCorrupt:       isLikelyCorrupt(peak, rms, activeRatio, float64(clippingCount)/float64(sampleCount)),
		ApproxSilent: peak < thresholds.MinPeakNormalized &&
			rms < thresholds.MinRMSNormalized &&
			activeRatio < thresholds.MinActiveSampleRatio,
	}
}

func TestActivityPreservesValidationExactly(t *testing.T) {
	rng := rand.New(rand.NewSource(42))
	for _, length := range []int{0, 1, 2, 1600, 32000, 320001} {
		data := make([]byte, length)
		rng.Read(data)
		for _, kind := range []int{0, 1, 2, 3} {
			for i := 0; i+1 < len(data); i += 2 {
				if kind == 1 {
					binary.LittleEndian.PutUint16(data[i:], 0)
				}
				if kind == 2 {
					binary.LittleEndian.PutUint16(data[i:], 32000)
				}
				if kind == 3 {
					binary.LittleEndian.PutUint16(data[i:], uint16(i))
				}
			}
			r := Result{Data: data, ByteCount: len(data), Format: "s16", Channels: 1, SampleRate: 16000}
			got := AnalyzeActivity(r, DefaultActivityThresholds())
			want := referenceAnalyzeActivity(r, DefaultActivityThresholds())
			if !reflect.DeepEqual(got, want) {
				t.Fatal("activity math changed")
			}
		}
	}
}
func TestActivityDoesNotAllocate(t *testing.T) {
	r := Result{Data: make([]byte, 32000), Format: "s16", Channels: 1}
	if n := testing.AllocsPerRun(10, func() { AnalyzeActivity(r, DefaultActivityThresholds()) }); n != 0 {
		t.Fatalf("allocations %v", n)
	}
}
