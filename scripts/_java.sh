# Shared helpers for scripts: locate the repo root and the portable JDK.
# Sourced, not executed.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JDK_DIR="$(ls -d "$REPO_ROOT"/tools/jdk-21* 2>/dev/null | head -n 1)"
if [ -z "$JDK_DIR" ]; then
  echo "portable JDK not found under $REPO_ROOT/tools (expected tools/jdk-21*)" >&2
  exit 1
fi
if [ -x "$JDK_DIR/bin/java.exe" ]; then JAVA="$JDK_DIR/bin/java.exe"; else JAVA="$JDK_DIR/bin/java"; fi
JENA_HOME="$REPO_ROOT/tools/apache-jena-5.5.0"
FUSEKI_HOME="$REPO_ROOT/tools/apache-jena-fuseki-5.5.0"

# Convert a path for the JVM: Windows form under Git Bash/Cygwin, unchanged elsewhere.
to_native() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

# file: URL for a local path (C:/x -> file:///C:/x, /x -> file:///x).
file_url() {
  local p; p="$(to_native "$1")"
  case "$p" in /*) printf 'file://%s' "$p" ;; *) printf 'file:///%s' "$p" ;; esac
}

# Absolute path for $1 resolved against the current cwd (target need not exist).
abs_path() {
  case "$1" in
    /*|[A-Za-z]:*|\\*) printf '%s' "$1" ;;
    *) printf '%s/%s' "$PWD" "$1" ;;
  esac
}
