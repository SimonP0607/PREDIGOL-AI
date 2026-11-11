# q4: EVALUACIÓN ÚNICA del protocolo proto-int-b09-v1 (sin base de datos ni red).
set -u
D=/tmp/lab_b09
sha256sum $D/ia_lab_b09_eventos.py
IMG=$(docker inspect -f '{{.Config.Image}}' predigol-worker)
echo "image=$IMG start=$(date -u +%FT%TZ)"
docker run --rm --network none -v $D:/lab --entrypoint python "$IMG" /lab/ia_lab_b09_eventos.py /lab --out /lab/results.json > $D/results.txt 2>&1
echo "rc=$? end=$(date -u +%FT%TZ)"
wc -c $D/results.txt $D/results.json
