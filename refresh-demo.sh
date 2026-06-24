#!/usr/bin/env bash
set -euo pipefail

demo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src_dir="$(cd "$demo_dir/.." && pwd)"

copy_file() {
  local src_rel="$1"
  local dest_rel="$2"
  install -D -m 0644 "$src_dir/$src_rel" "$demo_dir/$dest_rel"
}

mkdir -p "$demo_dir/templates"

copy_file ".dockerignore" ".dockerignore"
copy_file "Dockerfile" "Dockerfile"
copy_file "app.py" "app.py"
copy_file "index_runtime.py" "index_runtime.py"
copy_file "requirements.txt" "requirements.txt"

for template_path in "$src_dir"/templates/*.html; do
  install -D -m 0644 "$template_path" "$demo_dir/templates/$(basename "$template_path")"
done

sed -i -f "$demo_dir/sanitize-app.sed" "$demo_dir/app.py"
sed -i -f "$demo_dir/sanitize-templates.sed" "$demo_dir/templates/index.html"

printf 'Refreshed demo Aurora files in %s\n' "$demo_dir"
