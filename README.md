# practica2-agentes

La práctica tendrá varios componentes:

- Un scrapper en python que, dada una película, obtenga un diccionario con la información de la misma: nota, número de votos, sinopsis, director y duración. Se utilizará IMDB, aunque se admiten alternativas.
- Un skill de alexa que utilizará el scrapper para, cuando el usuario le pida algún dato de una pelicula (por ejemplo: ¿cuál es la nota de 2001?), le conteste con el dato.
- Otro scrapper que obtenga la cartelera de cine de Madrid (por ejemplo de https://www.ecartelera.com) e integre esta información con la proporcionada por el scrapper anterior. Este scrapper se ejecutará todos los lunes a las 9:00 (usar cron) y enviará el resultado por telegram o por mail.
- Utilizando un perfil del usuario que valore cada género, filtre la nota por ese perfil. Por ejemplo "Ciencia ficción: 6" dejaría pasar el filtro a las películas que siendo de ciencia ficción tengan más de un 6.

**Entregable**
Deberéis proporcionar un archivo .zip que incluya los siguientes ficheros:

- Un fichero .py que reciba por línea de comandos el nombre de la película a consultar y devuelva el valor de los campos.
- El fichero .py de la lambda de alexa.
- Un vídeo (o un enlace al mismo) demostrando el funcionamiento del skill de Alexa programado.
- Cualquier otro código fuente generado.
- Un enlace a las conversaciones mantenidas con el LLM.

**Criterios de Evaluación**
- Correctitud y completitud de los datos extraídos.
- Eficiencia en la descarga y manejo de datos.
- Calidad y claridad del código.
- Funcionalidades adicionales accesibles a través de argumentos del ejecutable (por ejemplo, indicar el campo que deseamos para que devuelva sólo ese).
