#!/bin/bash
# Run a command (default: kiro-cli acp) in a bubblewrap sandbox rooted at the current directory.
# The whole filesystem is read-only. Writable: the current directory, Kiro's own state, a private /tmp
# (also used as the Go build cache). Hidden: credential dirs, the user runtime dir, the docker socket.
# The environment is reduced to a short allow list.
set -euo pipefail
dir="$PWD"
k="$HOME/.local/share/kiro-cli"
args=(--ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --die-with-parent --unshare-pid
      --bind "$dir" "$dir" --chdir "$dir")

# Kiro state is writable; its executables stay read-only so nothing persists outside the run.
args+=(--bind "$k" "$k")
for f in bun node tui.js shell bun.sha256 node.sha256 tui.js.sha256; do
  [ -e "$k/$f" ] && args+=(--ro-bind "$k/$f" "$k/$f")
done
for d in sessions session-index logs tasks spec-sessions cloud-cache workspace-roots; do
  [ -d "$HOME/.kiro/$d" ] && args+=(--bind "$HOME/.kiro/$d" "$HOME/.kiro/$d")
done

# Credentials and sockets that would let a command act as the user elsewhere.
for d in .aws .ssh .kube .gnupg .docker .config/gh .config/glab-cli .config/gcloud .azure; do
  [ -d "$HOME/$d" ] && args+=(--tmpfs "$HOME/$d")
done
for f in .netrc .git-credentials; do
  [ -e "$HOME/$f" ] && args+=(--ro-bind /dev/null "$HOME/$f")
done
[ -d "/run/user/$(id -u)" ] && args+=(--tmpfs "/run/user/$(id -u)")
for s in /run/docker.sock /run/containerd/containerd.sock; do
  [ -S "$s" ] && args+=(--ro-bind /dev/null "$s")
done

env_args=(--clearenv --setenv HOME "$HOME" --setenv USER "${USER:-}" --setenv PATH "$PATH"
          --setenv LANG "${LANG:-C.UTF-8}" --setenv TERM "${TERM:-dumb}" --setenv GOCACHE /tmp/go-build
          --setenv GOFLAGS "${GOFLAGS:-}" --setenv GOPRIVATE "${GOPRIVATE:-}" --setenv GONOSUMDB "${GONOSUMDB:-}")

if [ $# -eq 0 ]; then set -- kiro-cli acp; fi
exec bwrap "${args[@]}" "${env_args[@]}" "$@"
