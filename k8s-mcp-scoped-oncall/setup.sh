#!/bin/sh
# Fetch the released Kubernetes MCP server, add the Tenuo check, build it.
set -eu
cd "$(dirname "$0")"
VERSION=v4.1.9
if [ ! -d server ]; then
  git clone -q --depth 1 --branch "$VERSION" https://github.com/Flux159/mcp-server-kubernetes.git server
fi
cd server
git checkout -q -- src/index.ts
cp ../tenuo-authz.ts src/tenuo-authz.ts
git apply ../index.ts.patch
npm install --silent
npm install --silent --no-save @tenuo/core@0.3.2-beta.0
npm run build --silent
echo "built server/dist/index.js ($VERSION + Tenuo check)"
