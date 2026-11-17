# Ejemplos del almacén de noticias (IA-080, AD-G01)

`C-06/noticia.public.json` es la «noticia individual» de C-06 (pantalla 09 del plan de UX) construida **solo** con lo que devuelven
las lecturas de `fbi.news.readers` sobre `news.items` + `news.item_entities` (y su historia). Lo comprueba
`tests/integration/test_news_store_db.py::test_c06_is_served_from_news_items_and_news_item_entities`.

Datos ficticios, direcciones en `.invalid`. No es el contrato registrado de Intelligence: el modelo de C-06, con su versión y su prueba de no fuga, lo entregó AD-G07
(IA-121) en `tests/fixtures/contracts/intelligence/C-06/`.
