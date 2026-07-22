#!/usr/bin/env bash
# Reproduces docs/LOAD_TESTING.md's Kubernetes HPA demo end to end: stands up
# a local kind cluster, deploys chat-service with its HorizontalPodAutoscaler
# (infra/k8s/21-chat-service.yaml), drives real load through /chat/dummy, and
# asserts the HPA actually scales replicas up under load and back down once
# idle - not just that the manifest exists.
#
# Slow (several minutes: cluster creation, image build/load, load test,
# scale-down settling) and heavier than the other scripts. Requires kind,
# kubectl, docker, k6. Tears down its own cluster on exit either way.
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh
REPO_ROOT="$(cd ../.. && pwd)"

echo "=== 60: Kubernetes HPA actually scales chat-service up and back down ==="

for bin in kind kubectl k6 docker; do
  if ! command -v "$bin" > /dev/null 2>&1; then
    fail "$bin is not installed - skipping this test"
    summary; exit 1
  fi
done

CLUSTER="llm-obs-hpa-test"
cleanup() {
  info "tearing down the kind cluster"
  kind delete cluster --name "$CLUSTER" > /dev/null 2>&1 || true
}
trap cleanup EXIT

info "creating kind cluster (this takes ~30-60s)"
if ! kind create cluster --name "$CLUSTER" --config "$REPO_ROOT/infra/k8s/kind-config.yaml" > /dev/null 2>&1; then
  fail "kind create cluster failed"
  summary; exit 1
fi
pass "kind cluster created"

info "installing metrics-server (patched for kind's self-signed kubelet certs)"
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml > /dev/null 2>&1
kubectl patch deployment metrics-server -n kube-system --type='json' \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]' > /dev/null 2>&1
kubectl -n kube-system rollout status deployment/metrics-server --timeout=90s > /dev/null 2>&1

info "building and loading the chat-service image into kind"
if ! docker build -q -f "$REPO_ROOT/apps/chat-service/Dockerfile" -t llm-obs/chat-service:0.1.0 "$REPO_ROOT" > /tmp/hpa_build.log 2>&1; then
  fail "docker build failed - see /tmp/hpa_build.log (often a transient registry/DNS issue, not a code problem):"
  tail -5 /tmp/hpa_build.log
  summary; exit 1
fi
pass "chat-service image built"
if ! kind load docker-image llm-obs/chat-service:0.1.0 --name "$CLUSTER" > /dev/null 2>&1; then
  fail "kind load docker-image failed"
  summary; exit 1
fi

info "deploying namespace, config, postgres, redis, kafka, migration, chat-service+HPA"
kubectl apply -f "$REPO_ROOT/infra/k8s/00-namespace.yaml" -f "$REPO_ROOT/infra/k8s/01-config.yaml" > /dev/null
kubectl apply -f "$REPO_ROOT/infra/k8s/10-postgres.yaml" -f "$REPO_ROOT/infra/k8s/11-redis.yaml" \
  -f "$REPO_ROOT/infra/k8s/12-kafka.yaml" > /dev/null
kubectl -n llm-observability wait --for=condition=ready pod -l app=postgres --timeout=120s > /dev/null 2>&1
kubectl apply -f "$REPO_ROOT/infra/k8s/20-migrate-job.yaml" > /dev/null
kubectl -n llm-observability wait --for=condition=complete job -l app.kubernetes.io/part-of=llm-observability --timeout=90s > /dev/null 2>&1 || true
kubectl apply -f "$REPO_ROOT/infra/k8s/21-chat-service.yaml" > /dev/null

info "waiting for chat-service pods to be ready"
if kubectl -n llm-observability wait --for=condition=ready pod -l app=chat-service --timeout=120s > /dev/null 2>&1; then
  pass "chat-service deployment is ready"
else
  fail "chat-service pods never became ready - can't proceed with the load test"
  kubectl -n llm-observability get pods
  summary; exit 1
fi

initial_replicas=$(kubectl -n llm-observability get deployment chat-service -o jsonpath='{.spec.replicas}')
info "initial replica count: $initial_replicas"

info "port-forwarding chat-service and driving load (800 VUs, 150s) - this takes a few minutes"
kubectl -n llm-observability port-forward svc/chat-service 8010:8001 > /dev/null 2>&1 &
PF_PID=$!
sleep 3

k6 run -e BASE_URL=http://localhost:8010 -e VUS=800 -e DURATION=150s "$REPO_ROOT/load-tests/k6/dummy.js" > /tmp/hpa_k6_output.log 2>&1 &
K6_PID=$!

# Watch for scale-up while the load test runs.
scaled_up=""
for _ in $(seq 1 40); do
  current=$(kubectl -n llm-observability get deployment chat-service -o jsonpath='{.status.replicas}' 2>/dev/null || echo "$initial_replicas")
  if [ "$current" -gt "$initial_replicas" ]; then
    scaled_up="yes"
    info "scaled up: $initial_replicas -> $current replicas"
    break
  fi
  sleep 5
done

wait "$K6_PID" 2>/dev/null || true
kill "$PF_PID" 2>/dev/null || true

if [ -n "$scaled_up" ]; then
  pass "HPA scaled chat-service up under load ($initial_replicas -> $current replicas)"
else
  fail "HPA never scaled chat-service up during the load test"
fi

peak_replicas="$current"

info "load test finished; watching for scale-down back toward minReplicas (this takes several minutes - HPA's stabilization window)"
scaled_down=""
for _ in $(seq 1 36); do  # up to ~9 minutes
  current=$(kubectl -n llm-observability get deployment chat-service -o jsonpath='{.status.replicas}' 2>/dev/null || echo "$peak_replicas")
  if [ "$current" -lt "$peak_replicas" ]; then
    scaled_down="yes"
    info "scale-down observed: $peak_replicas -> $current replicas"
    break
  fi
  sleep 15
done

if [ -n "$scaled_down" ]; then
  pass "HPA scaled chat-service back down once idle ($peak_replicas -> $current replicas)"
else
  fail "HPA never scaled back down within the observation window - possible repeat of the memory-request/idle-utilization bug documented in docs/LOAD_TESTING.md (check 'kubectl describe hpa chat-service -n llm-observability')"
fi

summary
