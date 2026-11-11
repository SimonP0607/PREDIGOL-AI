# q3: reconstruye el script de análisis subido en trozos, lo verifica y ejecuta SOLO el inventario (no calcula movimientos de precio).
set -u
D=/tmp/lab_b09
cat $D/s.b64.00 $D/s.b64.01 $D/s.b64.02 | tr -d '\n' | base64 -d | gunzip > $D/ia_lab_b09_eventos.py
sha256sum $D/ia_lab_b09_eventos.py
IMG=$(docker inspect -f '{{.Config.Image}}' predigol-worker)
echo "image=$IMG"
docker run --rm --network none -v $D:/lab --entrypoint python "$IMG" -c "import numpy, sys; print('numpy', numpy.__version__, sys.version.split()[0])"
docker run --rm --network none -v $D:/lab --entrypoint python "$IMG" /lab/ia_lab_b09_eventos.py /lab --inventory --out /lab/inventory.json
echo "rc=$?"
