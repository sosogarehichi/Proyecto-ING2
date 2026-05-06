from flask import Blueprint, request, jsonify
from flask_cors import cross_origin
import mercadopago
import traceback
import uuid
import os

pagos_bp = Blueprint("pagos", __name__)

CORS_ORIGIN = os.getenv('CORS_ORIGIN', 'http://localhost:5173')

# Reemplazá con tu Access Token real de Mercado Pago (modo sandbox o producción)
sdk = mercadopago.SDK(os.getenv('MERCADO_PAGO_ACCESS_TOKEN'))

# Endpoint para crear preferencia de pago
@pagos_bp.route("/pagar", methods=["POST"])
@cross_origin(origin=CORS_ORIGIN)
def crear_preferencia():
    try:
        data = request.get_json()

        # Generar un identificador único para el seguimiento del pago
        external_ref = str(uuid.uuid4())

        preference_data = {
            "items": [{
                "title": f"Reserva vehículo {data['nombre_vehiculo']}",
                "quantity": 1,
                "unit_price": float(data["monto_total"]),
                "currency_id": "ARS"
            }],
            "external_reference": external_ref
            # No incluimos back_urls ni auto_return
        }

        preference = sdk.preference().create(preference_data)

        if "init_point" not in preference["response"]:
            return jsonify({"error": "No se pudo generar el enlace de pago"}), 500

        return jsonify({
            "init_point": preference["response"]["init_point"],
            "external_reference": external_ref
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@pagos_bp.route("/status/<external_reference>", methods=["GET"])
@cross_origin(origin=CORS_ORIGIN)
def verificar_pago(external_reference):
    try:
        payment_search = sdk.payment().search({
            "external_reference": external_reference
        })

        payments = payment_search["response"]["results"]

        if not payments:
            return jsonify({"status": "pending"})

        for payment in payments:
            if payment["status"] == "approved":
                return jsonify({"status": "approved"})

        return jsonify({"status": "pending"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
