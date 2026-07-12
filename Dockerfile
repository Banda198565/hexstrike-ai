# Multi-stage build for hexstrike-osint-agent
FROM golang:1.22-alpine AS builder

RUN apk add --no-cache ca-certificates git

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download

COPY cmd/ cmd/
COPY internal/ internal/

RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -trimpath -ldflags="-s -w" -o /out/osint-agent ./cmd/osint-agent/

FROM alpine:3.20

RUN apk add --no-cache ca-certificates tzdata \
    && addgroup -S osint && adduser -S -G osint osint

WORKDIR /app
COPY --from=builder /out/osint-agent /app/osint-agent

USER osint:osint

# Process stays alive while background monitors run.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ps -o args | grep -q '[o]sint-agent' || exit 1

ENTRYPOINT ["/app/osint-agent"]
