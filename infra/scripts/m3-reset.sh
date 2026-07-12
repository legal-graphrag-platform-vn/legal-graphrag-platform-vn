#!/usr/bin/env bash
set -euo pipefail

container="graphrag-neo4j-m3"
image="neo4j:5.26.28-community"
volume="graphrag-neo4j-m3-data"
compose_file="docker-compose.m3.yml"
project="graphrag-m3"

[[ "${RUN_M3_DESTRUCTIVE:-}" == "1" ]] || { echo "Refusing reset: RUN_M3_DESTRUCTIVE=1 is required" >&2; exit 2; }
[[ "${CONFIRM_M3_RESET:-}" == "YES" ]] || { echo "Refusing reset: CONFIRM_M3_RESET=YES is required" >&2; exit 2; }
[[ -f "$compose_file" ]] || { echo "Missing frozen compose file: $compose_file" >&2; exit 2; }

if docker inspect "$container" >/dev/null 2>&1; then
  actual_image="$(docker inspect "$container" --format '{{.Config.Image}}')"
  http_port="$(docker inspect "$container" --format '{{(index (index .HostConfig.PortBindings "7474/tcp") 0).HostPort}}')"
  bolt_port="$(docker inspect "$container" --format '{{(index (index .HostConfig.PortBindings "7687/tcp") 0).HostPort}}')"
  data_mount="$(docker inspect "$container" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')"
  [[ "$actual_image" == "$image" ]] || { echo "Container image mismatch: $actual_image" >&2; exit 2; }
  [[ "$http_port" == "7475" ]] || { echo "Container HTTP port mismatch: $http_port" >&2; exit 2; }
  [[ "$bolt_port" == "7688" ]] || { echo "Container Bolt port mismatch: $bolt_port" >&2; exit 2; }
  [[ "$data_mount" == "$volume" ]] || { echo "Container data volume mismatch: $data_mount" >&2; exit 2; }
fi

if docker volume inspect "$volume" >/dev/null 2>&1; then
  compose_project="$(docker volume inspect "$volume" --format '{{index .Labels "com.docker.compose.project"}}')"
  [[ "$compose_project" == "$project" ]] || { echo "Volume project mismatch: $compose_project" >&2; exit 2; }
fi

docker compose --project-name "$project" -f "$compose_file" down
docker volume rm "$volume" 2>/dev/null || true
echo "Reset disposable M3 runtime only: $container / $volume"
