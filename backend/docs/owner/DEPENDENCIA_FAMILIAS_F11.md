# Cuánto dependen entre sí los goles, los córners y las tarjetas de un mismo partido (F11.6) · guía del propietario

*Escrita el 24 de octubre de 2026. Es una medición: solo lee la base de datos (partidos ya terminados), no hace peticiones al proveedor, no usa IA y no cambia ningún modelo, precio, combinada ni pick. **Lo que imprime no cambia la regla de «una selección por partido»**: relajarla, si algún día se hace, es decisión tuya.*

## 1. En pocas palabras

* **La pregunta del plan:** ¿se pueden juntar en una combinada dos selecciones del mismo partido de familias distintas (por ejemplo «más de 2,5 goles» y «más de 9,5 córners») multiplicando sus probabilidades como si no tuvieran nada que ver?
* **Hoy la respuesta es que no, no sin más.** Medido con 3 años de partidos terminados (59.252 con goles, córners y tarjetas conocidos), comparando cada partido solo con los de su misma competición y semestre:
  * Los **totales** (más/menos de goles, de córners y de tarjetas) casi no dependen entre sí: correlación de −0,021 a −0,028. Multiplicar sus probabilidades se equivoca poco (**1,6 % de mediana, 5,6 % como mucho**), pero ese poco es del tamaño del **2 %** de margen que se le exige a una combinada: de las 33 parejas de totales, ninguna queda demostrada despreciable (27 dudosas y 6 materiales).
  * Lo que depende **mucho** es **quién tiene más**: cuando un equipo tiene más córners, el otro suele tener más tarjetas (correlación −0,149 entre la diferencia de córners y la de tarjetas) y el equipo que gana suele tener menos (−0,114 con los goles). Ahí el producto se equivoca hasta un **15,2 %**.
  * «Ambos marcan» con «más de 4,5 tarjetas» ocurren juntos un 5,9 % más de lo que dice el producto.
* **No se propone relajar la regla.** Ninguna familia tiene hoy un pick defendible (`FAMILIAS_VS_MERCADO_F11.md`, `CRITERIO_FAMILIAS_F11.md`), la dependencia entre los «quién tiene más» es grande y los totales están en el margen. Esta medición queda como la tabla que habría que usar si algún día se relaja (sección 6).

## 2. Qué se mide

Cada selección de una combinada es una pregunta de sí o no sobre un partido. Se miden **17 preguntas** de las tres familias (goles a 90 minutos, córners, tarjetas contadas como líneas):

* **Totales por encima de una línea:** goles 1,5 / 2,5 / 3,5; córners 8,5 / 9,5 / 10,5 / 11,5; tarjetas 3,5 / 4,5 / 5,5.
* **Ambos marcan.**
* **Quién tiene más:** que el local o el visitante tenga más córners, más tarjetas o más goles (ganar). El empate es de nadie.

Para cada pareja de preguntas de **dos familias distintas** (96 parejas) hay cuatro casos: ocurren **ambas**, **solo la primera**, **solo la segunda** o **ninguna**. De cada caso se mide el **factor de dependencia**: cuántas veces ocurrió contra cuántas habría ocurrido si las dos preguntas no tuvieran nada que ver. La probabilidad real de un caso es el producto de las probabilidades de sus dos selecciones **por su factor**.

Un ejemplo con los números reales: «más de 2,5 goles» y «más de 9,5 córners» ocurren juntos con un factor de **×0,980**. El producto sobrestima esa combinación un 2 %, y una combinada que el producto valora en **+2 %** (el mínimo que se le exige) valdría en realidad **−0,1 %**: no queda nada del margen. En «más de 2,5 goles» sin «más de 9,5 córners» el factor es **×1,020** y la misma combinada valdría **+4,1 %**.

## 3. Cómo leer el resultado

* **Se compara dentro de cada grupo.** Una competición con muchos goles tiene también muchos córners y muchas tarjetas, y un semestre se parece más a sí mismo que a otro: mezclarlos haría parecer dependencia lo que es el nivel de la competición, que el pronóstico ya conoce. Cada cifra compara los partidos de **una competición en un semestre** (grupos de al menos 30 partidos; los más pequeños se dejan fuera y se dice cuántos) y suma los grupos. En esta lectura la diferencia es pequeña (la sección 4 muestra las dos cifras), pero es la comparación correcta.
* **Los intervalos** (95 %) salen de **400 remuestreos** con semilla 11 en los que se sortean **días de una competición** (los partidos que una competición jugó el mismo día van juntos: comparten tiempo, árbitros y fin de semana). Con los mismos datos salen siempre los mismos números. Una prueba del código lo comprueba con partidos simulados sin ninguna dependencia: el error que estima el remuestreo coincide con el real y los intervalos del 95 % cubren el cero casi siempre que deben.
* **El veredicto de cada caso** compara su factor, con su intervalo, con la **tolerancia de 2 %** (la misma que el margen que se le pide a una combinada, `PARLAY_MIN_EV`): todo el intervalo dentro, el producto se equivoca menos que eso; todo el intervalo fuera, se equivoca más y se dice en qué sentido; si el intervalo no lo resuelve, es dudoso.
* **El veredicto de la pareja** es el de su peor caso: `negligible` (despreciable, los cuatro casos dentro de la tolerancia), `material` (algún caso se equivoca por más, con seguridad) o `borderline` (dudosa: la dependencia es del tamaño de la tolerancia y los datos no dicen de qué lado).
* **Son 96 parejas a la vez.** Sin corregir por comparaciones múltiples, entre 96 parejas independientes puede salir alguna `material` por azar (una de 96 en una simulación de prueba). Las que tienen una correlación de ±0,05 o más no son azar.

## 4. Lo medido (24 de octubre de 2026)

Ventana de 3 años (27-oct-2023 a 24-oct-2026), solo competiciones seguidas. Tenían goles 89.239 partidos, córners 63.127 y tarjetas 62.154; los tres a la vez, 61.403, y 59.252 tras dejar fuera 2.151 en grupos de menos de 30 (549 grupos, 21.211 días de competición). El resultado completo, con las 96 parejas y sus intervalos, está en `DEPENDENCIA_FAMILIAS_F11_resultado.json` (la salida de `--json`).

**Correlación de los propios conteos dentro de cada grupo** (entre corchetes, el intervalo; mezclando todos los partidos saldría lo de la derecha):

| Conteos | Correlación | Mezclados |
|---|---|---|
| goles totales con córners totales | −0,021 [−0,029, −0,014] | −0,006 |
| goles totales con tarjetas totales | −0,028 [−0,036, −0,020] | −0,048 |
| córners totales con tarjetas totales | −0,024 [−0,033, −0,016] | −0,035 |
| diferencia de goles con diferencia de córners | +0,058 [+0,049, +0,065] | +0,061 |
| diferencia de goles con diferencia de tarjetas | −0,114 [−0,122, −0,107] | −0,115 |
| diferencia de córners con diferencia de tarjetas | −0,149 [−0,157, −0,142] | −0,151 |

**Las 96 parejas:** 21 son `negligible`, 51 `borderline` y 24 `material`. Por tipo:

| Tipo de pareja | Parejas | `negligible` | `borderline` | `material` | Mayor desvío del producto |
|---|---|---|---|---|---|
| total con total | 33 | 0 | 27 | 6 | 5,6 % |
| total con «quién tiene más» | 40 | 16 | 17 | 7 | 5,8 % |
| «quién tiene más» con «quién tiene más» | 12 | 2 | 2 | 8 | 15,2 % |
| «ambos marcan» con un total | 7 | 1 | 3 | 3 | 8,3 % |
| «ambos marcan» con «quién tiene más» | 4 | 2 | 2 | 0 | 1,5 % |

**Las parejas más habituales** (factor de cada caso; ×1,000 sería independencia):

| Primera selección | Segunda selección | φ | Ambas | Solo la primera | Solo la segunda | Ninguna | Veredicto |
|---|---|---|---|---|---|---|---|
| más de 2,5 goles | más de 9,5 córners | −0,022 | ×0,980 | ×1,020 | ×1,022 | ×0,979 | `borderline` |
| más de 2,5 goles | más de 4,5 tarjetas | −0,011 | ×0,989 | ×1,009 | ×1,012 | ×0,990 | `borderline` |
| más de 9,5 córners | más de 4,5 tarjetas | −0,021 | ×0,977 | ×1,018 | ×1,022 | ×0,982 | `borderline` |
| ambos marcan | más de 9,5 córners | +0,010 | ×1,009 | ×0,991 | ×0,989 | ×1,010 | `negligible` |
| ambos marcan | más de 4,5 tarjetas | +0,059 | ×1,059 | ×0,952 | ×0,934 | ×1,055 | `material` |
| gana el local | el local tiene más córners | −0,002 | ×0,998 | ×1,002 | ×1,001 | ×0,998 | `negligible` |
| gana el visitante | el visitante tiene más córners | +0,009 | ×1,017 | ×0,990 | ×0,992 | ×1,004 | `borderline` |
| gana el local | el local tiene más tarjetas | −0,054 | ×0,917 | ×1,043 | ×1,066 | ×0,966 | `material` |
| gana el visitante | el visitante tiene más tarjetas | −0,059 | ×0,903 | ×1,080 | ×1,043 | ×0,965 | `material` |
| el local tiene más córners | el local tiene más tarjetas | −0,086 | ×0,890 | ×1,057 | ×1,125 | ×0,934 | `material` |
| el visitante tiene más córners | el visitante tiene más tarjetas | −0,096 | ×0,865 | ×1,111 | ×1,080 | ×0,934 | `material` |
| el local tiene más córners | el visitante tiene más tarjetas | +0,094 | ×1,095 | ×0,921 | ×0,890 | ×1,090 | `material` |
| el visitante tiene más córners | el local tiene más tarjetas | +0,086 | ×1,152 | ×0,920 | ×0,910 | ×1,047 | `material` |

Leído en palabras: **los goles y los córners casi no se tocan** (ganar y tener más córners son independientes); **las tarjetas se reparten al revés que el juego**: el equipo que domina (más córners, más goles) recibe menos tarjetas que el otro, y los partidos con goles de los dos equipos tienen algo más de tarjetas.

## 5. Lo que esta medición no dice

* **No condiciona por equipos.** Un local fuerte hace a la vez más goles, más córners y menos tarjetas, y los pronósticos de las familias sí conocen a los equipos: lo que queda entre dos selecciones **después** de sus pronósticos es menos que esto. Las cifras son una **cota superior** de la dependencia que los pronósticos no explican: una pareja despreciable aquí lo es; una material puede deberse en parte a los equipos. Medir lo que queda necesita pronósticos de las familias guardados durante semanas (desde el 24-oct a las 04:13 UTC), y será una lectura posterior.
* **No hay precios.** El proveedor no ofrece, en la lista de mercados guardada el 23-oct, ningún mercado que junte goles con córners o tarjetas, así que el sistema no guarda precios de combinaciones entre familias de un mismo partido. Esto dice lo que valdría una combinada **justa**, no lo que pagaría ninguna casa (que no tiene por qué aceptarla).
* **Solo 17 preguntas.** Otras líneas o selecciones (por mitad, por equipo, hándicaps) no están medidas.
* **Solo partidos con estadísticas.** Los córners y las tarjetas salen de las estadísticas por equipo (sin prórroga); los goles, del marcador a los 90 minutos. Un 31 % de los partidos con marcador no tiene las tres cosas y no entra.

## 6. Qué haría falta si algún día se relaja la regla (decisión tuya)

La regla de hoy (`parlay-v5`): una selección por partido, ningún equipo repetido, como mucho dos por competición, y la probabilidad conjunta se corrige solo con dependencias **negativas significativas** entre partidos de una misma competición y día: *una estimación puede empeorar una combinada, nunca mejorarla*. Si se relajara para familias distintas del mismo partido, esta medición sugiere seguir el mismo principio:

* admitir como mucho **una selección por familia** y por partido, y solo parejas de **totales** (las parejas con «quién tiene más» dependen demasiado);
* aplicar el factor medido de un caso **solo cuando todo su intervalo está por debajo de 1** (el producto sobrestima), y no aplicar nada cuando está por encima (el producto se queda corto, que es el lado prudente);
* exigir además que el valor de la combinada supere el 2 % **con el factor aplicado**, y repetir esta medición antes de hacerlo.

Recomendación: **no hacerlo todavía.** Ninguna familia tiene un pick defendible y aún no se ha medido la dependencia que queda después de los pronósticos.

## 7. Cómo se repite

```
python -m scripts.families dependence                       # 3 años, lee la base de datos (solo lectura)
python -m scripts.families dependence --days 365 --top 20   # solo el último año, 20 parejas en el texto
python -m scripts.families dependence --json                # el resultado completo (las 96 parejas)
python -m scripts.families dependence --csv-goals g.csv.gz --csv-corners c.csv.gz --csv-cards k.csv.gz   # desde tres exportaciones de `export`
```

Las tres exportaciones son `export --measure goals_ft`, `corners_ft` y `cards_lines_ft` con la misma ventana. El cálculo con 60.000 partidos tarda unos 10 segundos; no hay trabajo programado: la medición se repite cuando quieras y da lo mismo con los mismos datos. Se propone repetirla cuando haya semanas de pronósticos de las familias guardados.
