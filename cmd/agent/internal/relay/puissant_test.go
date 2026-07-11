package relay

import (
	"context"
	"testing"
)

func TestPuissantPublicFallback(t *testing.T) {
	r := DefaultPuissantRelay()
	r.AllowPublicFallback = true
	res, err := r.Submit(context.Background(), SubmitRequest{RawTx: []byte{0x02}, ChainID: 56})
	if err != nil {
		t.Fatal(err)
	}
	if res.Strategy != StrategyPublic {
		t.Fatalf("strategy=%s", res.Strategy)
	}
}

func TestPuissantNoFallbackFails(t *testing.T) {
	r := DefaultPuissantRelay()
	r.AllowPublicFallback = false
	_, err := r.Submit(context.Background(), SubmitRequest{RawTx: []byte{0x02}})
	if err == nil {
		t.Fatal("expected error without fallback")
	}
}
