// Seleccionamos el botón del DOM por su ID.
// ¿Por qué y para qué?: Necesitamos escuchar el evento 'click' del usuario para detonar la petición HTTP hacia Flask.
const btnFinalizar = document.getElementById('btn-finalizar-dia');

if (btnFinalizar) {
    // Agregamos el 'event listener' asíncrono para interceptar el click.
    btnFinalizar.addEventListener('click', async () => {
        
        // 1. Bloqueo de UI (User Interface)
        // ¿Por qué y para qué?: Deshabilitar el botón previene que el operador haga "doble click" accidental, lo cual duplicaría la carga en el servidor y enviaría dos correos vía n8n.
        btnFinalizar.disabled = true;
        btnFinalizar.innerText = 'Generando Reporte...';

        try {
            // 2. Ejecución de la Petición al Servidor
            // ¿Por qué y para qué?: Usamos fetch() nativo. Al ser una ruta que modifica la base de datos (cierra viajes), el estándar dicta usar el método POST.
            const respuesta = await fetch('/admin/cierre_diario', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            // Verificamos si el servidor respondió con error (ej. error 500 de base de datos).
            if (!respuesta.ok) {
                throw new Error(`Error en el servidor: ${respuesta.status}`);
            }

            // 3. Extracción del Archivo Binario (Blob)
            // ¿Por qué y para qué?: El navegador no lee un PDF como texto. El Blob (Binary Large Object) empaqueta los bytes crudos del archivo que envió Flask (io.BytesIO) para que JS lo pueda manipular en RAM.
            const blob = await respuesta.blob();

            // 4. Creación de Enlace Dinámico
            // ¿Por qué y para qué?: Necesitamos un "link" local (http://...) para que el navegador del móvil sepa de dónde descargar el archivo.
            const urlDescarga = window.URL.createObjectURL(blob);

            // 5. Simulación de Descarga
            // ¿Por qué y para qué?: HTML usa las etiquetas <a> para descargar archivos. Al crearlo en memoria, asignarle la URL y simular un click, obligamos a Android/iOS a abrir el diálogo de descarga sin que el usuario cambie de pestaña.
            const enlaceInvisible = document.createElement('a');
            enlaceInvisible.href = urlDescarga;
            
            // Asignamos el nombre físico que tendrá el PDF al guardarse en la carpeta "Descargas" del celular.
            enlaceInvisible.download = `Reporte_ArtTours_${new Date().toISOString().split('T')[0]}.pdf`;

            // Añadimos el enlace al documento, lo "clickeamos", y lo destruimos.
            document.body.appendChild(enlaceInvisible);
            enlaceInvisible.click();
            document.body.removeChild(enlaceInvisible);

            // 6. Limpieza de Memoria
            // ¿Por qué y para qué?: Liberamos la URL temporal de la RAM del navegador. Previene fugas de memoria (memory leaks) si la pestaña queda abierta por días.
            window.URL.revokeObjectURL(urlDescarga);

            // Restauramos el estado visual del botón.
            btnFinalizar.innerText = 'Día Finalizado Exitosamente';
            
        } catch (error) {
            // Manejo de contingencias (caída de red del celular o fallo del servidor).
            console.error('Fallo operativo en cierre de día:', error);
            btnFinalizar.innerText = 'Error. Reintentar Cierre';
            btnFinalizar.disabled = false;
        }
    });
}