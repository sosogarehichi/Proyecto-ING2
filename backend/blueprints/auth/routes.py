from flask import Blueprint, request, jsonify,session
from datetime import datetime, date
from models.usuario import Usuario
from flask_mail import Message
from extensions import mail, db
from flask_cors import CORS
from models.empleado import Empleado
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt_identity
)
import bcrypt
import random
import os

auth_bp = Blueprint('auth', __name__)
CORS(auth_bp, supports_credentials=True, origins=[os.getenv('CORS_ORIGIN', 'http://localhost:5173')])
codigos_2fa = {}
codigos_contraseña = {}

# -------------------- UTILS --------------------
def calcular_edad(fecha_nac):
    today = date.today()
    return today.year - fecha_nac.year - ((today.month, today.day) < (fecha_nac.month, fecha_nac.day))


# -------------------- REGISTRO --------------------
@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()

    if Usuario.query.filter_by(email=data['email']).first():
        return jsonify({'message': 'Correo ya registrado en el sistema'}), 400

    try:
        fecha_nac = datetime.strptime(data['fecha_nacimiento'], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'message': 'Formato de fecha inválido, debe ser YYYY-MM-DD'}), 400

    if calcular_edad(fecha_nac) < 18:
        return jsonify({'message': 'El usuario debe ser mayor de edad'}), 400

    if len(data['contrasena']) < 8:
        return jsonify({'message': 'La contraseña debe tener al menos 8 caracteres'}), 400

    hashed_password = bcrypt.hashpw(data['contrasena'].encode('utf-8'), bcrypt.gensalt())

    nuevo_usuario = Usuario(
        nombre=data['nombre'],
        apellido=data['apellido'],
        dni=data['dni'],
        fecha_nacimiento=fecha_nac,
        telefono=data['telefono'],
        email=data['email'],
        contrasena=hashed_password.decode('utf-8'),
        es_admin=False,
        es_empleado=False
    )

    db.session.add(nuevo_usuario)
    db.session.commit()

    return jsonify({'message': 'Usuario registrado con éxito'}), 201


# -------------------- LOGIN --------------------
@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    user = Usuario.query.filter_by(email=email).first()
    if not user or not bcrypt.checkpw(password.encode('utf-8'), user.contrasena.encode('utf-8')):
        return jsonify({'message': 'Los datos ingresados son incorrectos'}), 401
    
    if user.es_admin:
        codigo = str(random.randint(1000, 9999))
        codigos_2fa[email] = codigo

        msg = Message(
            subject="Código de verificación",
            recipients=[email],
            body=f"El código de verificación es: {codigo}"
        )
        try:
            mail.send(msg)
        except Exception as e:
            print("Error enviando mail:", e)

        return jsonify({
            "message": "Se ha enviado un código de verificación",
            "require_2fa": True
        }), 200

    # ✅ Usuario común → generar token correctamente
    access_token = create_access_token(identity=str(user.id))
    if user.es_admin:
            rol = 1
    elif user.es_empleado:
            rol = 2
    else:
            rol = 3
    
    return jsonify({
        'message': 'Inicio de sesión exitoso',
        'access_token': access_token,
        'rol': rol,
        'require_2fa': False
    }), 200


# -------------------- VERIFICAR 2FA --------------------
@auth_bp.route('/verificar-2fa', methods=['POST'])
def verificar_2fa():
    data = request.get_json()
    email = data.get('email')
    codigo_ingresado = data.get('codigo')

    codigo_valido = codigos_2fa.get(email)
    if not codigo_valido:
        return jsonify({"message": "No se ha solicitado código de verificación para este usuario"}), 400

    if codigo_ingresado != codigo_valido:
        return jsonify({"message": "Código de verificación incorrecto"}), 401

    usuario = Usuario.query.filter_by(email=email).first()
    if not usuario:
        return jsonify({"message": "Usuario no encontrado"}), 404

    del codigos_2fa[email]

    # ✅ Generar token correctamente
    access_token = create_access_token(identity=str(usuario.id))


    return jsonify({
    "message": "Inicio de sesión exitoso",
    "access_token": access_token,
    "usuario_id": usuario.id,
    "rol": "admin" if usuario.es_admin else "cliente",
    "require_2fa": False
}), 200



# -------------------- PERFIL PROTEGIDO --------------------
@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def me():
    usuario_id = get_jwt_identity()
    usuario = Usuario.query.get(usuario_id)
    if not usuario:
        return jsonify({'message': 'Usuario no encontrado'}), 404

    return jsonify({
        'email': usuario.email,
        'es_admin': usuario.es_admin,
        'es_empleado': usuario.es_empleado
    }), 200

@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.pop('usuario_id', None)
    return jsonify({'message': 'Sesión cerrada exitosamente'}), 200


@auth_bp.route('/profile', methods=['GET'])
@jwt_required()
def profile():
    try:
        user_id = get_jwt_identity()
    except Exception as e:
        return jsonify({"error": str(e)}), 422

    user = Usuario.query.get(user_id)
    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 404

    return jsonify({
        "id": user.id, 
        "nombre": user.nombre,
        "apellido": user.apellido,
        "rol": user.rol, 
        "email": user.email,
        "dni": user.dni,
        "telefono": user.telefono,
        "activo": user.activo,
        "fecha_nacimiento": user.fecha_nacimiento.isoformat() if user.fecha_nacimiento else None
    })

@auth_bp.route('/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    user_id = get_jwt_identity()

    user = Usuario.query.get(user_id)
    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 404

    data = request.get_json()
    new_email = data.get('email', user.email)

    if new_email != user.email:
        existing_user_with_new_email = Usuario.query.filter(
            Usuario.email == new_email,
            Usuario.id != user_id
        ).first()
        if existing_user_with_new_email:
            return jsonify({"message": "Este email ya está registrado por otro usuario."}), 409

    user.nombre = data.get('nombre', user.nombre)
    user.apellido = data.get('apellido', user.apellido)
    user.email = new_email
    user.dni = data.get('dni', user.dni)
    user.telefono = data.get('telefono', user.telefono)
    user.fecha_nacimiento = data.get('fecha_nacimiento', user.fecha_nacimiento)
    db.session.commit()

    return jsonify({"message": "Perfil actualizado correctamente"})

# -------------------- REGISTRO EMPLEADO--------------------
@auth_bp.route('/register-empleado', methods=['POST'])
@jwt_required()
def register_empleado():
    data = request.get_json()
    user_id = get_jwt_identity()
    current_user = Usuario.query.get(int(user_id))

    if not current_user or not current_user.es_admin:
        return jsonify({'message': 'Solo un administrador puede crear empleados'}), 403

    usuario_existente = Usuario.query.filter_by(email=data['email']).first()

    if usuario_existente:
        if usuario_existente.activo:
            return jsonify({'message': 'El correo ya está registrado en un usuario activo'}), 400
        else:
            return jsonify({
                'message': f"El correo '{usuario_existente.email}' ya existe pero el usuario está eliminado. "
                        "Puedes recuperarlo desde la sección de empleados inactivos."
            }), 400

    try:
        fecha_nac = datetime.strptime(data['fecha_nacimiento'], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'message': 'Formato de fecha inválido, debe ser YYYY-MM-DD'}), 400

    if calcular_edad(fecha_nac) < 18:
        return jsonify({'message': 'El empleado debe ser mayor de edad'}), 400

    if len(data['contrasena']) < 8:
        return jsonify({'message': 'La contraseña debe tener al menos 8 caracteres'}), 400

    hashed_password = bcrypt.hashpw(data['contrasena'].encode('utf-8'), bcrypt.gensalt())

    nuevo_usuario = Usuario(
        nombre=data['nombre'],
        apellido=data['apellido'],
        dni=data['dni'],
        fecha_nacimiento=fecha_nac,
        telefono=data['telefono'],
        email=data['email'],
        contrasena=hashed_password.decode('utf-8'),
        es_admin=False,
        es_empleado=True,
        activo=True
    )

    db.session.add(nuevo_usuario)
    db.session.flush()

    sucursal_id = data.get('sucursal_id')
    if not sucursal_id:
        return jsonify({'message': 'Falta el ID de sucursal para el empleado'}), 400

    cantidad_empleados = Empleado.query.count() + 1
    numero_empleado = f"EMP{cantidad_empleados:04d}"

    nuevo_empleado = Empleado(
        id=nuevo_usuario.id,
        numero_empleado=numero_empleado,
        sucursal_id=sucursal_id
    )
    db.session.add(nuevo_empleado)
    db.session.commit()

    return jsonify({'message': 'Empleado registrado con éxito'}), 201

@auth_bp.route('/recuperar-cuenta', methods=['POST', 'OPTIONS'])
def recuperar_cuenta():
    if request.method == 'OPTIONS':
        response = jsonify({'message': 'Preflight OK'})
        response.headers.add('Access-Control-Allow-Origin', os.getenv('CORS_ORIGIN', 'http://localhost:5173'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'POST,OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200

    data = request.get_json()
    email = data.get('email')
    usuario = Usuario.query.filter_by(email=email).first()

    if not usuario:
        return jsonify({'message': 'Usuario no encontrado'}), 404

    if usuario.activo:
        return jsonify({'message': 'La cuenta ya está activa'}), 400

    if usuario.rol != 3:
        return jsonify({'message': 'Solo los clientes pueden recuperar su cuenta'}), 403

    # Generar y guardar código
    codigo = str(random.randint(100000, 999999))
    codigos_2fa[email] = codigo

    msg = Message(
        subject="Recuperación de cuenta - Código de verificación",
        recipients=["sofiagarehichi@gmail.com"],
        body=f"Tu código para recuperar la cuenta es: {codigo}"
    )
    try:
        mail.send(msg)
    except Exception as e:
        print("Error enviando mail:", e)

    response = jsonify({'message': 'Se ha enviado un código de verificación al correo'})
    response.headers.add('Access-Control-Allow-Origin', os.getenv('CORS_ORIGIN', 'http://localhost:5173'))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response, 200

@auth_bp.route('/verificar-codigo-recuperacion', methods=['POST', 'OPTIONS'])
def verificar_codigo_recuperacion():
    if request.method == 'OPTIONS':
        response = jsonify({'message': 'Preflight OK'})
        response.headers.add('Access-Control-Allow-Origin', os.getenv('CORS_ORIGIN', 'http://localhost:5173'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'POST,OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200

    data = request.get_json()
    email = data.get('email')
    codigo_ingresado = data.get('codigo')

    if email not in codigos_2fa:
        return jsonify({'message': 'No se ha solicitado recuperación para este correo'}), 400

    if codigos_2fa[email] != codigo_ingresado:
        return jsonify({'message': 'Código incorrecto'}), 401

    usuario = Usuario.query.filter_by(email=email).first()
    if not usuario:
        return jsonify({'message': 'Usuario no encontrado'}), 404

    if usuario.rol != 3:
        return jsonify({'message': 'Solo los clientes pueden recuperar su cuenta'}), 403

    usuario.activo = True
    db.session.commit()
    del codigos_2fa[email]

    access_token = create_access_token(identity=str(usuario.id))

    response = jsonify({
        'message': 'Cuenta reactivada con éxito',
        'access_token': access_token,
        'nombre': usuario.nombre,
        'apellido': usuario.apellido
    })
    response.headers.add('Access-Control-Allow-Origin', os.getenv('CORS_ORIGIN', 'http://localhost:5173'))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response, 200

    # -------------------- RECUPERAR CONTRASEÑA --------------------
@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json()
    email = data.get('email')
    # chequeo que el mail esté en la base de datos
    user = Usuario.query.filter_by(email=email).first()
    if not user:
        return jsonify({'message': 'El email no está registrado.'}), 404

    # Generar código de 6 dígitos
    codigo = str(random.randint(100000, 999999))
    codigos_contraseña[email] = codigo

    msg = Message(
        subject="Código de recuperación de contraseña",
        recipients=[email],
        body=f"Tu código de recuperación es: {codigo}"
    )
    try:
        mail.send(msg)
    except Exception as e:
        print("Error enviando mail:", e)

    usuario = Usuario.query.filter_by(email=email).first()
    if not usuario:
        return jsonify({"message": "Usuario no encontrado"}), 404

    # Aquí se debería generar un token de recuperación y enviarlo por email
    return jsonify({"message": "Se ha enviado un email de recuperación"}), 200


# -------------------- VERIFICAR CÓDIGO DE RECUPERACIÓN --------------------
@auth_bp.route('/verify-reset-code', methods=['POST'])
def verify_reset_code():
    data = request.get_json()
    email = data.get('email')
    codigo = data.get('codigo')

    codigo_valido = codigos_contraseña.get(email)
    if not codigo_valido:
        return jsonify({"message": "No se ha solicitado recuperación para este email"}), 400

    if codigo != codigo_valido:
        return jsonify({"message": "Código incorrecto"}), 401

    return jsonify({"message": "Código correcto"}), 200


# -------------------- CAMBIAR CONTRASEÑA --------------------
@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json()
    email = data.get('email')
    codigo = data.get('codigo')
    nueva_contrasena = data.get('nueva_contrasena')

    # Validar longitud mínima
    if not nueva_contrasena or len(nueva_contrasena) < 8:
        return jsonify({"message": "La contraseña debe tener al menos 8 caracteres"}), 400

    codigo_valido = codigos_contraseña.get(email)
    if not codigo_valido or codigo != codigo_valido:
        return jsonify({"message": "Código inválido"}), 401

    usuario = Usuario.query.filter_by(email=email).first()
    if not usuario:
        return jsonify({"message": "Usuario no encontrado"}), 404

    usuario.contrasena = bcrypt.hashpw(nueva_contrasena.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    db.session.commit()

    # Elimina el código usado
    del codigos_contraseña[email]

    return jsonify({"message": "Contraseña restablecida correctamente"}), 200
