#!/bin/zsh
# Parallel range download of the remaining bytes of a resumable file.
# Usage: parallel_fetch.sh <url> <output_file> <total_size> <segments>
set -u
url=$1
out=$2
total=$3
segs=$4

cur=$(stat -f%z "$out")
remaining=$(( total - cur ))
chunk=$(( (remaining + segs - 1) / segs ))
echo "have=$cur remaining=$remaining chunk=$chunk"

fetch_seg() {
  local i=$1 start=$2 end=$3
  local seg="$out.seg$i"
  local want=$(( end - start + 1 ))
  # resume an existing segment if present
  local have=0
  [[ -f "$seg" ]] && have=$(stat -f%z "$seg")
  while (( have < want )); do
    curl -sSL --retry 8 --retry-delay 3 -C - \
      -r $(( start + have ))-$end \
      -o "$seg.tmp" "$url" || true
    # append what we got onto seg
    [[ -f "$seg.tmp" ]] && { cat "$seg.tmp" >> "$seg"; rm -f "$seg.tmp"; }
    have=0; [[ -f "$seg" ]] && have=$(stat -f%z "$seg")
    (( have < want )) && { echo "seg$i retrying ($have/$want)"; sleep 3; }
  done
  echo "seg$i done ($have bytes)"
}

pids=()
for i in $(seq 0 $(( segs - 1 ))); do
  start=$(( cur + i * chunk ))
  end=$(( start + chunk - 1 ))
  (( end >= total )) && end=$(( total - 1 ))
  (( start > end )) && continue
  fetch_seg $i $start $end &
  pids+=($!)
  sleep 0.4
done
fail=0
for p in $pids; do wait $p || fail=1; done
(( fail != 0 )) && { echo "SEGMENTS-FAILED"; exit 1; }

# append segments in order
for i in $(seq 0 $(( segs - 1 ))); do
  seg="$out.seg$i"
  [[ -f "$seg" ]] && cat "$seg" >> "$out" && rm -f "$seg"
done

final=$(stat -f%z "$out")
echo "final_size=$final expected=$total"
if [[ $final -eq $total ]]; then
  echo "PARALLEL-FETCH-DONE"
else
  echo "SIZE-MISMATCH"; exit 1
fi
