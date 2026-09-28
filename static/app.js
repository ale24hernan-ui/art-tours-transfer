// =========================================
// 1. CAPTURA DE ELEMENTOS DEL HTML (EL DOM)
// =========================================
// Siempre debemos declarar nuestras variables al inicio del archivo para que JavaScript las conozca.

// Buscamos el campo donde el cliente escribe los pasajeros.
const inputPasajeros = document.getElementById('pasajeros');
// Buscamos la lista desplegable de los vehículos.
const selectVehiculo = document.getElementById('vehiculo');
// Buscamos la lista desplegable del lugar de origen.
const selectOrigen = document.getElementById('origen');
// Buscamos la lista desplegable del lugar de destino.
const selectDestino = document.getElementById('destino');
// Buscamos el contenedor invisible que mostrará el precio total.
const contenedorPrecio = document.getElementById('contenedor-precio');
// Buscamos el texto exacto donde inyectaremos el símbolo de dólar y el número.
const precioTotalTexto = document.getElementById('precio-total');


// =========================================
// 2. BASES DE DATOS TEMPORALES (DICCIONARIOS)
// =========================================

// Definimos las capacidades máximas reales de la flota actual para validar reservas[cite: 12].
const capacidadesFlota = {
    'auto': 4,
    'van': 8, // Basado en la capacidad de tu camioneta tipo Van actual[cite: 12].
    'autobus': 40
};

// Matriz temporal que define cuánto cuesta una ruta dependiendo del vehículo.
const matrizPrecios = {
    'aeropuerto_cun-hotel_playa_carmen': {
        'auto': 50,    
        'van': 80,     
        'autobus': 250 
    },
    'aeropuerto_cun-hotel_tulum': {
        'auto': 90,
        'van': 130,
        'autobus': 350
    }
};


// =========================================
// 3. FUNCIONES Y LÓGICA DE CÁLCULO
// =========================================

// Esta función se encarga de cruzar la ruta seleccionada con el vehículo para calcular el costo.
function calcularTarifa() {
    // Extraemos el texto que el cliente seleccionó en las listas.
    let origen = selectOrigen.value;
    let destino = selectDestino.value;
    let vehiculo = selectVehiculo.value;

    // Si falta alguno de los 3 datos, detenemos la función y mantenemos el precio oculto.
    if (!origen || !destino || !vehiculo) {
        contenedorPrecio.style.display = 'none';
        return; 
    }

    // Creamos la "llave" combinando el origen y destino con un guion (ej: "aeropuerto_cun-hotel_playa_carmen").
    let ruta = origen + '-' + destino;

    // Si la ruta y el vehículo existen en nuestra matriz, mostramos el precio.
    if (matrizPrecios[ruta] && matrizPrecios[ruta][vehiculo]) {
        let precio = matrizPrecios[ruta][vehiculo];
        // Inyectamos el precio con el formato correcto en el HTML.
        precioTotalTexto.innerText = '$' + precio + ' USD';
        // Hacemos que el contenedor del precio sea visible.
        contenedorPrecio.style.display = 'block';
    } else {
        // Si la ruta no está registrada, mostramos un mensaje por defecto.
        precioTotalTexto.innerText = 'Cotización Especial';
        contenedorPrecio.style.display = 'block';
    }
}


// =========================================
// 4. ESCUCHADORES DE EVENTOS (EVENT LISTENERS)
// =========================================

// EVENTO A: Cuando el cliente escribe o borra un número en el campo de pasajeros.
inputPasajeros.addEventListener('input', function() {
    // Convertimos el texto ingresado a un número entero.
    let pax = parseInt(this.value);
    
    // Si el usuario borró el número (dejó vacío el campo), detenemos el bloque para evitar errores.
    if (isNaN(pax)) return; 
    
    let vehiculoSeleccionado = selectVehiculo.value;

    // Si el cliente ya había escogido un vehículo, evaluamos si el nuevo número de pasajeros cabe en él.
    if (vehiculoSeleccionado) {
        let capacidadActual = capacidadesFlota[vehiculoSeleccionado];
        
        // Si los pasajeros superan la capacidad, forzamos un salto al vehículo más grande que los soporte.
        if (pax > capacidadActual) {
            if (pax <= 4) selectVehiculo.value = 'auto';
            else if (pax <= 8) selectVehiculo.value = 'van';
            else selectVehiculo.value = 'autobus';
        }
    } else {
        // Si no había vehículo seleccionado, le asignamos automáticamente el adecuado.
        if (pax <= 4) selectVehiculo.value = 'auto';
        else if (pax <= 8) selectVehiculo.value = 'van';
        else selectVehiculo.value = 'autobus';
    }
    
    // Una vez ajustado el vehículo, recalculamos el precio final.
    calcularTarifa();
});

// EVENTO B: Cuando el cliente cambia manualmente el vehículo en la lista desplegable.
selectVehiculo.addEventListener('change', function() {
    let pax = parseInt(inputPasajeros.value);
    let nuevoVehiculo = this.value;
    let capacidadMaxima = capacidadesFlota[nuevoVehiculo];

    // Si el campo de pasajeros estaba vacío, lo autocompletamos con "1".
    if (isNaN(pax)) {
        inputPasajeros.value = 1;
    } 
    // Si el cliente tenía ej. 40 personas y escoge un "Auto", reducimos el número de personas al máximo del Auto (4).
    else if (pax > capacidadMaxima) {
        inputPasajeros.value = capacidadMaxima;
    }
    
    // Recalculamos el precio total.
    calcularTarifa();
});

// EVENTOS C y D: Cuando el cliente cambia el Origen o el Destino, recalculamos el precio inmediatamente.
selectOrigen.addEventListener('change', calcularTarifa);
selectDestino.addEventListener('change', calcularTarifa);