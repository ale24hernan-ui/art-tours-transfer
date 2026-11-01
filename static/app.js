// =========================================
// 1. CAPTURA DE ELEMENTOS DEL HTML (EL DOM)
// =========================================
const inputPasajeros = document.getElementById('pasajeros');
const selectVehiculo = document.getElementById('vehiculo');
// ¿Por qué?: Ajustamos los IDs para que coincidan exactamente con los de tu index.html original.
const selectOrigen = document.getElementById('origen_select');
const selectDestino = document.getElementById('destino_select');
const contenedorPrecio = document.getElementById('contenedor-precio');
const precioTotalTexto = document.getElementById('precio-total');

// =========================================
// 2. CONFIGURACIÓN DE FLOTA
// =========================================
const capacidadesFlota = {
    'auto': 4,
    'van': 8,
    'autobus': 40
};

// =========================================
// 3. LÓGICA DE COTIZACIÓN ASÍNCRONA (SaaS)
// =========================================
// ¿Por qué?: Convertimos la función a 'async' para poder esperar la respuesta del servidor (await fetch).
async function calcularTarifa() {
    let origen = selectOrigen.value;
    let destino = selectDestino.value;
    // Si no tienes el select de vehículo visible aún, forzamos 'Van 8 Pax' por defecto.
    let vehiculo = selectVehiculo ? selectVehiculo.value : 'Van 8 Pax'; 

    if (!origen || !destino) {
        contenedorPrecio.style.display = 'none';
        return; 
    }

    // ¿Por qué?: Inyectamos un estado de carga UI.
    // ¿Para qué?: Previene que el cliente piense que la página se congeló durante los 200ms de latencia de red.
    precioTotalTexto.innerText = 'Calculando tarifa...';
    contenedorPrecio.style.display = 'block';

    try {
        // ¿Por qué?: Disparamos un POST a la API REST de tu servidor Flask.
        // ¿Para qué?: Mantenemos la lista de precios oculta en el backend, consultando únicamente la ruta que el cliente solicita.
        const respuesta = await fetch('/api/v1/cotizar', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ origen: origen, destino: destino, vehiculo: vehiculo })
        });

        const data = await respuesta.json();

        // ¿Por qué?: Evaluamos la respuesta de la base de datos PostgreSQL.
        if (data.status === 'success') {
            precioTotalTexto.innerText = '$' + data.precio + ' ' + data.moneda;
        } else {
            precioTotalTexto.innerText = 'Cotización Especial (Vía WhatsApp)';
        }
    } catch (error) {
        // Fallback defensivo si se cae el internet del cliente.
        precioTotalTexto.innerText = 'Cotización Especial';
    }
}

// =========================================
// 4. ESCUCHADORES DE EVENTOS
// =========================================
inputPasajeros.addEventListener('input', function() {
    let pax = parseInt(this.value);
    if (isNaN(pax)) return; 
    
    // Validamos que selectVehiculo exista en el DOM antes de manipularlo
    if (selectVehiculo) {
        let vehiculoSeleccionado = selectVehiculo.value;
        if (vehiculoSeleccionado) {
            let capacidadActual = capacidadesFlota[vehiculoSeleccionado];
            if (pax > capacidadActual) {
                if (pax <= 4) selectVehiculo.value = 'auto';
                else if (pax <= 8) selectVehiculo.value = 'van';
                else selectVehiculo.value = 'autobus';
            }
        } else {
            if (pax <= 4) selectVehiculo.value = 'auto';
            else if (pax <= 8) selectVehiculo.value = 'van';
            else selectVehiculo.value = 'autobus';
        }
    }
    calcularTarifa();
});

if (selectVehiculo) {
    selectVehiculo.addEventListener('change', function() {
        let pax = parseInt(inputPasajeros.value);
        let capacidadMaxima = capacidadesFlota[this.value];
        if (isNaN(pax)) inputPasajeros.value = 1;
        else if (pax > capacidadMaxima) inputPasajeros.value = capacidadMaxima;
        calcularTarifa();
    });
}

// ¿Por qué?: Cada vez que el cliente cambia la ruta, detonamos el fetch a PostgreSQL automáticamente.
selectOrigen.addEventListener('change', calcularTarifa);
selectDestino.addEventListener('change', calcularTarifa);