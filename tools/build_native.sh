#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
  else
    PYTHON="$(command -v python)"
  fi
fi
CMAKE_BIN="$("$PYTHON" -c 'import cmake, os; print(os.path.join(os.path.dirname(cmake.__file__), "data", "bin", "cmake"))')"
PYBIND11_DIR="$("$PYTHON" -m pybind11 --cmakedir)"
"$CMAKE_BIN" -S . -B build/native \
  -DDNGSCAN_BUILD_NATIVE=ON \
  -DCMAKE_BUILD_TYPE=Release \
  -DPython_EXECUTABLE="$PYTHON" \
  -Dpybind11_DIR="$PYBIND11_DIR"
"$CMAKE_BIN" --build build/native -j"$(sysctl -n hw.ncpu 2>/dev/null || nproc)"
cp "build/native/cpp/_dngscan_fast"*.so dngscan/
echo "Installed native module into dngscan/"
