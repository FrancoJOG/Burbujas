import os


from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.conf import settings

import unicodedata
import re


from django.core.cache import cache  # Para usar Redis

import pandas as pd
import pymongo
import json

from django.core.paginator import Paginator
from collections import defaultdict, Counter
from pymongo.errors import AutoReconnect


LISTA_ESTADOS = [
    'Aguascalientes', 'Baja California', 'Baja California Sur', 'Campeche',
    'Chiapas', 'Chihuahua', 'Ciudad de México', 'Coahuila', 'Colima',
    'Durango', 'Estado de México', 'Guanajuato', 'Guerrero', 'Hidalgo',
    'Jalisco', 'Michoacán', 'Morelos', 'Nayarit', 'Nuevo León', 'Oaxaca',
    'Puebla', 'Querétaro', 'Quintana Roo', 'San Luis Potosí', 'Sinaloa',
    'Sonora', 'Tabasco', 'Tamaulipas', 'Tlaxcala', 'Veracruz', 'Yucatán',
    'Zacatecas', 'SIN ESTADO'  # Agregamos 'SIN ESTADO' a la lista
]

# Conexión a MongoDB
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client['data']  # Nombre de la base de datos
collection = db['sistema6']  # Nombre de la colección

def home(request):
    return render(request, 'burbujas/index.html')

def normalize_text(text):
    return ''.join(
        c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn'
    ).upper()


def lista_servidores_publicos(request):
    # Obtener los filtros desde la URL (GET)
    nombre = normalize_text(request.GET.get('nombre', '').strip())
    empresa = normalize_text(request.GET.get('empresa', '').strip())
    estado = normalize_text(request.GET.get('estado', '').strip())
    page_number = request.GET.get('page', '1')

    # Crear una clave única para la caché basada en los filtros y la página
    cache_key = f"servidores_publicos_{nombre}_{empresa}_{estado}_page_{page_number}"
    
    # Intentar obtener los datos del caché
    cached_data = cache.get(cache_key)
    
    # Depuración: Eliminar la clave del caché para forzar una consulta a MongoDB
    cache.delete(cache_key)  # <<<<< Este es el lugar correcto

    if cached_data:
        # Si hay datos en el caché, los usamos
        servidores_publicos = json.loads(cached_data)
        print("Usando datos de Redis (cache).")
    else:
        # Crear un diccionario de filtros
        filtros = {
            "declaracion.interes.participacion.ninguno": False,
            "declaracion.interes.participacion.participacion": {"$exists": True, "$ne": []}
        }

        # Agregar los filtros dinámicamente si el usuario los proporciona
        if nombre:
            filtros.update({
                "declaracion.situacionPatrimonial.datosGenerales.nombre": {"$regex": nombre, "$options": "i"}
            })
        if empresa:
            filtros.update({
                "declaracion.interes.participacion.participacion.nombreEmpresaSociedadAsociacion": {"$regex": empresa, "$options": "i"}
            })
        if estado and estado != 'Todos':
            filtros.update({
                "declaracion.situacionPatrimonial.datosEmpleoCargoComision.domicilioMexico.entidadFederativa.valor": {"$regex": estado, "$options": "i"}
            })

        # Conectar a MongoDB y aplicar los filtros
        client = pymongo.MongoClient(settings.DATABASES['default']['CLIENT']['host'])
        db = client[settings.DATABASES['default']['NAME']]  # Conexión a la base de datos 'data'
        collection = db['sistema1']  # Conexión a la colección 'sistema1'

        data = list(collection.find(
            filtros,
            {
                "declaracion.situacionPatrimonial.datosGenerales": 1,  # Solo traer campos necesarios
                "declaracion.interes.participacion": 1
            }
        ))

        # Procesar los datos si es necesario
        servidores_publicos = []
        for servidor in data:
            try:
                servidores_publicos.append({
                    'nombre': servidor['declaracion']['situacionPatrimonial']['datosGenerales'].get('nombre', ''),
                    'primerApellido': servidor['declaracion']['situacionPatrimonial']['datosGenerales'].get('primerApellido', ''),
                    'segundoApellido': servidor['declaracion']['situacionPatrimonial']['datosGenerales'].get('segundoApellido', ''),
                    'participacion': servidor['declaracion']['interes'].get('participacion', [])
                })
            except KeyError as e:
                print(f"Error al procesar el servidor: {e}")

        # Guardar los datos en el caché por 24 horas (86,400 segundos)
        cache.set(cache_key, json.dumps(servidores_publicos), timeout=86400)
        print("Datos almacenados en Redis (cache).")
            
    # Verificar si no hay datos
    datos_disponibles = bool(servidores_publicos)

    # Paginación: Mostrar 20 servidores públicos por página
    paginator = Paginator(servidores_publicos, 20)
    page_obj = paginator.get_page(page_number)

    return render(request, 'burbujas/lista_servidores_publicos.html', {
        'page_obj': page_obj,
        'data': servidores_publicos,
        #'data': page_obj.object_list,
        'lista_estados': LISTA_ESTADOS,  # Pasamos la lista de estados
        'estado_seleccionado': estado,  # Pasamos el estado seleccionado
        'datos_disponibles': datos_disponibles,  # Bandera para datos disponibles
        'request': request
    })


def get_nested(dictionary, keys, default=None):
    """
    Obtiene valores anidados de un diccionario de forma segura.
    """
    for key in keys:
        if isinstance(dictionary, dict):
            dictionary = dictionary.get(key, default)
            if dictionary is None:
                return default
        else:
            return default
    return dictionary

def empresas_chart_view(request):
    estado_seleccionado = request.GET.get('estado', 'Todos')

    cache_key = f"empresas_chart_data_{estado_seleccionado}"
    cached_data = cache.get(cache_key)

    if cached_data:
        # Si encontramos los datos en caché, los usamos
        empresas_data = json.loads(cached_data)
    else:
        # Conexión a MongoDB
        client = pymongo.MongoClient("mongodb://localhost:27017/")
        db = client['data']  # Nombre de la base de datos

        collection_s1 = db['sistema1']
        collection_s6 = db['sistema6']

        # 1. Obtener los datos de sistema1 (declaraciones) y cargar en un DataFrame
        # Buscamos los servidores públicos y sus participaciones en empresas
        personas_s1_cursor = collection_s1.find(
            {
                "declaracion.interes.participacion.ninguno": False,
                "declaracion.interes.participacion.participacion": {"$exists": True, "$ne": []}
            },
            {
                "_id": 0,
                "declaracion.interes.participacion.participacion": 1
            }
        )

        # Convertir el cursor a una lista de diccionarios
        personas_s1_list = list(personas_s1_cursor)

        # Expandir las participaciones para obtener RFC y porcentaje de participación
        records_participaciones = []
        for persona in personas_s1_list:
            participaciones = get_nested(persona, ['declaracion', 'interes', 'participacion', 'participacion'], [])
            if isinstance(participaciones, dict):
                participaciones = [participaciones]
            elif not isinstance(participaciones, list):
                participaciones = []
            for participacion in participaciones:
                if not isinstance(participacion, dict):
                    continue
                rfc = participacion.get('rfc', '').strip().upper()
                porcentaje = participacion.get('porcentajeParticipacion', 0)
                if rfc:
                    # Filtrar RFCs válidos (opcional)
                    if not re.match(r'^[A-Z0-9]{12,13}$', rfc):
                        continue
                    records_participaciones.append({
                        'rfc': rfc,
                        'porcentajeParticipacion': porcentaje
                    })

        # Crear DataFrame de participaciones
        df_participaciones = pd.DataFrame(records_participaciones)
        if df_participaciones.empty:
            empresas_data = []
        else:
            # 2. Obtener los datos de sistema6 (licitaciones) y cargar en un DataFrame
            # Vamos a obtener las licitaciones que involucren a las empresas del paso anterior
            rfc_empresas = df_participaciones['rfc'].unique().tolist()

            # Pipeline para obtener las licitaciones
            pipeline = [
                {"$match": {"parties.identifier.id": {"$in": rfc_empresas}}},
                {"$unwind": "$parties"},
                {"$match": {"parties.identifier.id": {"$in": rfc_empresas}, "parties.roles": "supplier"}},
                {"$project": {
                    "_id": 0,
                    "ocid": 1,
                    "parties": 1,
                    "tender": 1,
                    "contracts": 1
                }}
            ]

            data_s6 = list(collection_s6.aggregate(pipeline))

            # Procesar los datos para obtener un DataFrame con las licitaciones
            records_licitaciones = []
            for item in data_s6:
                ocid = item.get('ocid', '')
                parties = item.get('parties', [])
                estado = 'SIN ESTADO'

                # Obtener el estado del comprador o entidad contratante
                for party in parties:
                    if not isinstance(party, dict):
                        continue
                    roles = party.get('roles', [])
                    if not isinstance(roles, list):
                        roles = [roles]
                    if 'buyer' in roles or 'procuringEntity' in roles:
                        estado = get_nested(party, ['address', 'region'], 'SIN ESTADO')
                        break

                # Filtrar por estado si se seleccionó uno
                if estado_seleccionado != 'Todos':
                    if estado_seleccionado != estado:
                        continue

                party_supplier = item.get('parties', {})
                if not isinstance(party_supplier, list):
                    party_supplier = [party_supplier]
                for party in party_supplier:
                    roles = party.get('roles', [])
                    if not isinstance(roles, list):
                        roles = [roles]
                    if 'supplier' in roles:
                        rfc = party.get('identifier', {}).get('id', '').strip().upper()
                        name = party.get('name', '')
                        break
                else:
                    continue  # Si no encontramos un supplier, pasamos al siguiente registro

                tender_title = get_nested(item, ['tender', 'title'], '')
                tender_description = get_nested(item, ['tender', 'description'], '')
                tender_date = get_nested(item, ['tender', 'tenderPeriod', 'startDate'], '')
                contracts = item.get('contracts', [])

                # Puede haber múltiples contratos
                if contracts:
                    for contract in contracts:
                        contract_id = contract.get('id', '')
                        contract_amount = get_nested(contract, ['value', 'amount'], 0)
                        contract_currency = get_nested(contract, ['value', 'currency'], '')
                        records_licitaciones.append({
                            'rfc': rfc,
                            'ocid': ocid,
                            'name': name,
                            'estado': estado,
                            'tender_title': tender_title,
                            'tender_description': tender_description,
                            'tender_date': tender_date,
                            'contract_id': contract_id,
                            'contract_amount': contract_amount,
                            'contract_currency': contract_currency
                        })
                else:
                    # Si no hay contratos, aún registramos la licitación
                    records_licitaciones.append({
                        'rfc': rfc,
                        'ocid': ocid,
                        'name': name,
                        'estado': estado,
                        'tender_title': tender_title,
                        'tender_description': tender_description,
                        'tender_date': tender_date,
                        'contract_id': '',
                        'contract_amount': 0,
                        'contract_currency': ''
                    })

            # Crear DataFrame de licitaciones
            df_licitaciones = pd.DataFrame(records_licitaciones)
            if df_licitaciones.empty:
                empresas_data = []
            else:
                # 3. Unir los DataFrames de participaciones y licitaciones
                df_empresas = pd.merge(df_participaciones, df_licitaciones, on='rfc', how='inner')

                # Agrupar por empresa (rfc) y obtener la información necesaria
                empresas_data = []
                for rfc, group in df_empresas.groupby('rfc'):
                    empresa = {
                        'rfc': rfc,
                        'porcentajeParticipacion': group['porcentajeParticipacion'].mean(),
                        'nombreEmpresa': group['name'].iloc[0],
                        'numeroLicitaciones': group['ocid'].nunique(),
                        'estado': group['estado'].iloc[0],
                        'licitaciones': group.to_dict('records')
                    }
                    empresas_data.append(empresa)

        # Guardamos el resultado en Redis durante 10 minutos (600 segundos)
        cache.set(cache_key, json.dumps(empresas_data), timeout=86400)

    # Paginación: Mostrar 20 empresas por página
    paginator = Paginator(empresas_data, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Serializa los datos en formato JSON para pasarlos al template
    data_json = json.dumps(list(page_obj.object_list))

    # Pasa los datos y el objeto de paginación al template
    return render(request, 'burbujas/empresas_chart.html', {
        'data': data_json,  # Pasamos los datos serializados en JSON
        'page_obj': page_obj,
        'lista_estados': ['Todos'] + LISTA_ESTADOS,  # Incluimos la lista de estados
        'estado_seleccionado': estado_seleccionado  # Pasamos el estado seleccionado
    })


def normalize_string(s):
    """
    Normaliza una cadena de texto eliminando acentos, caracteres especiales,
    puntuación y espacios extra, y convirtiendo a mayúsculas.
    """
    if not isinstance(s, str):
        return ''
    # Eliminar acentos y caracteres especiales
    s = ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )
    # Convertir a mayúsculas
    s = s.upper()
    # Eliminar puntuación y caracteres no alfanuméricos
    s = re.sub(r'[^A-Z0-9\s]', '', s)
    # Eliminar espacios extra
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def cruces_s1_s6_view(request):
    # Parámetro para filtrar RFCs válidos, inválidos o ambos
    filtro_rfc = request.GET.get('validos', 'both').lower()

    # Conexión a MongoDB
    client = pymongo.MongoClient(settings.DATABASES['default']['CLIENT']['host'])
    db = client[settings.DATABASES['default']['NAME']]

    # Definir las colecciones para S1 y S6
    collection_s1 = db['sistema1']
    collection_s6 = db['sistema6']

    # Obtener datos de sistema1 y cargar en un DataFrame
    personas_s1_cursor = collection_s1.find(
        {
            "declaracion.interes.participacion.ninguno": False,
            "declaracion.interes.participacion.participacion": {"$exists": True, "$ne": []}
        },
        {
            "_id": 0,
            "declaracion.situacionPatrimonial.datosGenerales": 1,
            "declaracion.interes.participacion.participacion": 1
        }
    )

    # Convertir el cursor a una lista de diccionarios
    personas_s1_list = list(personas_s1_cursor)
    records = []
    for persona in personas_s1_list:
        datos_generales = get_nested(persona, ['declaracion', 'situacionPatrimonial', 'datosGenerales'], {})
        participaciones = get_nested(persona, ['declaracion', 'interes', 'participacion', 'participacion'], [])
        if isinstance(participaciones, dict):
            participaciones = [participaciones]
        elif not isinstance(participaciones, list):
            participaciones = []
        for participacion in participaciones:
            if not isinstance(participacion, dict):
                continue
            rfc = participacion.get('rfc', '').strip().upper()
            if rfc:
                records.append({
                    'nombre': datos_generales.get('nombre', ''),
                    'primerApellido': datos_generales.get('primerApellido', ''),
                    'segundoApellido': datos_generales.get('segundoApellido', ''),
                    'rfc': rfc
                })

    # Crear DataFrame de personas
    df_personas = pd.DataFrame(records)
    if df_personas.empty:
        return render(request, 'burbujas/cruces_s1_s6.html', {
            'page_obj': [],
            'data': []
        })

    # Obtener datos de sistema6 y cargar en un DataFrame
    rfc_participaciones = df_personas['rfc'].unique().tolist()
    empresas_s6_cursor = collection_s6.find(
        {
            "parties.identifier.id": {"$in": rfc_participaciones}
        },
        {
            "_id": 0,
            "parties": 1
        }
    )

    # Expandir las parties
    empresas_s6_list = list(empresas_s6_cursor)
    records_empresas = []
    for empresa in empresas_s6_list:
        parties = empresa.get('parties', [])
        for party in parties:
            id_party = party.get('identifier', {}).get('id', '').strip().upper()
            name_party = party.get('name', '')
            if id_party in rfc_participaciones:
                records_empresas.append({
                    'rfcEmpresa': id_party,
                    'nombreEmpresa': name_party
                })

    # Crear DataFrame de empresas
    df_empresas = pd.DataFrame(records_empresas)
    if df_empresas.empty:
        return render(request, 'burbujas/cruces_s1_s6.html', {
            'page_obj': [],
            'data': []
        })

    # Cruzar los DataFrames utilizando el RFC como clave
    df_cruces = pd.merge(df_personas, df_empresas, left_on='rfc', right_on='rfcEmpresa', how='inner')
    if 'rfc_valido' not in df_cruces.columns:
        df_cruces['rfc_valido'] = df_cruces['rfc'].apply(
            lambda x: bool(re.match(r'^[A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{3}$', x))
        )

    # Filtrar según el parámetro 'filtro_rfc'
    if filtro_rfc == 'true':  # Mostrar solo válidos
        df_cruces = df_cruces[df_cruces['rfc_valido']]
    elif filtro_rfc == 'false':  # Mostrar solo inválidos
        df_cruces = df_cruces[~df_cruces['rfc_valido']]

    # Agrupar y resumir los datos
    df_cruces_grouped = df_cruces.groupby(
        ['nombre', 'primerApellido', 'segundoApellido', 'rfcEmpresa']
    ).agg(
        nombreEmpresa=('nombreEmpresa', 'first'),
        CantidadCoincidencias=('rfc', 'count')
    ).reset_index()

    # Convertir el DataFrame resultante a una lista de diccionarios
    cruces = df_cruces_grouped.to_dict('records')

    # Paginación
    paginator = Paginator(cruces, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'burbujas/cruces_s1_s6.html', {
        'page_obj': page_obj,
        'data': cruces
    })



def normalize_estado(estado):
    if not isinstance(estado, str):
        return 'SIN ESTADO'
    estado = estado.strip().title()
    return estado


def mapa_mexico_view(request):
    # Clave única para el caché
    cache_key = 'mapa_mexico_data'
    data_json = cache.get(cache_key)

    if data_json:
        # Si los datos están en caché, los usamos
        print("Usando datos de la caché.")
    else:
        print("Datos no encontrados en la caché, cargando desde archivo JSON...")
        try:
            # Ruta del archivo JSON exportado desde MongoDB Compass
            file_path = os.path.join(os.path.dirname(__file__), 'data', 'jal.json')

            # Leer los datos desde el archivo JSON
            print(f"Cargando datos desde: {file_path}")
            with open(file_path, 'r', encoding='utf-8') as f:
                data_s6 = json.load(f)
            
            print(f"Se han cargado {len(data_s6)} documentos desde el archivo JSON.")

            # Procesar los datos
            print("Procesando los datos obtenidos...")
            records = []
            estado_counter = Counter()  # Para contar cuántos registros tiene cada estado

            for idx, item in enumerate(data_s6):
                if idx % 1000 == 0:
                    print(f"Procesando documento {idx + 1} de {len(data_s6)}...")
                ocid = item.get('ocid', '')
                date = item.get('date', '')  # Fecha del proceso
                year = pd.to_datetime(date).year if date else None

                parties = item.get('parties', [])
                estado = 'SIN ESTADO'

                # Obtener el estado del comprador o entidad contratante
                for party in parties:
                    if not isinstance(party, dict):
                        continue
                    roles = party.get('roles', [])
                    if not isinstance(roles, list):
                        roles = [roles]
                    if 'buyer' in roles or 'procuringEntity' in roles:
                        estado_raw = get_nested(party, ['address', 'region'], 'SIN ESTADO')
                        estado = normalize_estado(estado_raw)
                        break

                # Incrementar el contador de registros para el estado
                estado_counter[estado] += 1

                # Obtener el monto de los contratos
                contracts = item.get('contracts', [])
                total_amount = 0
                for contract in contracts:
                    amount = get_nested(contract, ['value', 'amount'], 0)
                    
                    # Asegúrate de que 'amount' es un número antes de sumarlo
                    if isinstance(amount, (int, float)):
                        total_amount += amount
                    else:
                        print(f"Warning: El campo 'amount' no es numérico en el documento {idx + 1}, valor encontrado: {amount}")

                records.append({
                    'estado': estado,
                    'year': year,
                    'amount': total_amount
                })

            print("Creando DataFrame a partir de los registros procesados...")
            # Crear un DataFrame
            df = pd.DataFrame(records)
            print(f"DataFrame creado con {len(df)} registros.")

            # Manejar casos donde el año o estado es None
            print("Eliminando registros con valores nulos en 'year' o 'estado'...")
            df = df.dropna(subset=['year', 'estado'])
            print(f"DataFrame después de eliminar nulos tiene {len(df)} registros.")

            # Agrupar los datos por estado y año
            print("Agrupando datos por 'estado' y 'year' y calculando la suma de 'amount'...")
            df_grouped = df.groupby(['estado', 'year']).agg({'amount': 'sum'}).reset_index()
            print("Datos agrupados correctamente.")

            # Preparar los datos para el template
            print("Preparando datos para el template...")
            data_por_estado = defaultdict(list)
            for _, row in df_grouped.iterrows():
                estado = row['estado']
                year = int(row['year'])
                amount = row['amount']
                data_por_estado[estado].append({'year': year, 'amount': amount})

            # Imprimir cuántos estados y cuántos registros tiene cada uno
            print(f"Total de estados procesados: {len(estado_counter)}")
            for estado, count in estado_counter.items():
                print(f"Estado: {estado}, Registros: {count}")

            # Convertir a JSON para pasar al template
            print("Convirtiendo datos a formato JSON...")
            data_json = json.dumps(data_por_estado)

            # Guardar los datos en caché por 5 horas (5 horas * 60 minutos * 60 segundos = 18,000 segundos)
            print("Almacenando datos en caché por 5 horas...")
            cache.set(cache_key, data_json, timeout=86400)
            print("Datos almacenados en caché correctamente.")

        except Exception as e:
            print(f"Error al leer los datos desde el archivo JSON: {e}")
            # Manejar el error de forma apropiada, mostrando un mensaje en la página
            return render(request, 'burbujas/error.html', {
                'mensaje': 'Error al cargar los datos desde el archivo. Por favor, inténtalo de nuevo más tarde.'
            })

    print("Renderizando el template 'burbujas/mapa_mexico.html' con los datos procesados.")
    return render(request, 'burbujas/mapa_mexico.html', {
        'data': data_json
    })

from django.shortcuts import render
from django.conf import settings
from django.core.cache import cache
import re
import pandas as pd
import pymongo
import json
import random

def get_nested(dictionary, keys, default=None):
    for key in keys:
        if isinstance(dictionary, dict):
            dictionary = dictionary.get(key, default)
            if dictionary is None:
                return default
        else:
            return default
    return dictionary

def filtros_dinamicos(request):
    cache_key = 'filtros_dinamicos_data'
    cached_data = cache.get(cache_key)

    if cached_data:
        data = cached_data
    else:
        # Conexión a MongoDB
        client = pymongo.MongoClient(settings.DATABASES['default']['CLIENT']['host'])
        db = client[settings.DATABASES['default']['NAME']]
        collection_s1 = db['sistema1']
        collection_s6 = db['sistema6']

        # 1. Obtener datos de S1
        personas_s1_cursor = collection_s1.find(
            {
                "declaracion.interes.participacion.ninguno": False,
                "declaracion.interes.participacion.participacion": {"$exists": True, "$ne": []}
            },
            {
                "_id": 0,
                "declaracion.situacionPatrimonial.datosGenerales": 1,
                "declaracion.interes.participacion.participacion": 1
            }
        )
        personas_s1_list = list(personas_s1_cursor)

        records_participaciones = []
        for persona in personas_s1_list:
            datos_generales = get_nested(persona, ['declaracion', 'situacionPatrimonial', 'datosGenerales'], {})
            participaciones = get_nested(persona, ['declaracion', 'interes', 'participacion', 'participacion'], [])
            if isinstance(participaciones, dict):
                participaciones = [participaciones]
            elif not isinstance(participaciones, list):
                participaciones = []
            for p in participaciones:
                if not isinstance(p, dict):
                    continue
                rfc = p.get('rfc', '').strip().upper()
                if rfc and re.match(r'^[A-Z0-9]{12,13}$', rfc):
                    records_participaciones.append({'rfc': rfc})

        df_personas = pd.DataFrame(records_participaciones)
        if df_personas.empty:
            data = {'total_empresas':0, 'empresas':[]}
            cache.set(cache_key, data, timeout=86400)
            return render(request, 'burbujas/filtros_dinamicos.html', {
                'data': json.dumps(data) # Serializamos a JSON
            })

        # 2. Obtener datos de S6
        rfc_participaciones = df_personas['rfc'].unique().tolist()
        empresas_s6_cursor = collection_s6.find(
            {
                "parties.identifier.id": {"$in": rfc_participaciones}
            },
            {
                "_id": 0,
                "parties": 1,
                "tender":1,
                "contracts":1,
                "awards":1
            }
        )
        empresas_s6_list = list(empresas_s6_cursor)

        records_empresas = []
        for item in empresas_s6_list:
            parties = item.get('parties', [])
            if not isinstance(parties, list):
                continue

            tender = item.get('tender', {})
            procurementMethod = tender.get('procurementMethod', '')
            contracts = item.get('contracts', [])
            awards = item.get('awards', [])

            rfc_en_esta = []
            empresa_nombre = None

            for party in parties:
                if not isinstance(party, dict):
                    continue
                identifier = party.get('identifier', {})
                id_party = identifier.get('id', '').strip().upper()
                name_party = party.get('name', '')
                if id_party in rfc_participaciones:
                    rfc_en_esta.append(id_party)
                    empresa_nombre = name_party

            if empresa_nombre and rfc_en_esta:
                count_contratos = len(contracts)

                # Heurísticas de ejemplo
                cohecho = (procurementMethod.lower() in ['direct', 'limited'] and len(rfc_en_esta) > 0)

                total_monto = 0
                for c in contracts:
                    val = c.get('value', {}).get('amount',0)
                    if isinstance(val,(int,float)):
                        total_monto += val
                desvio = total_monto > 1000000

                conflictoInteres = (len(rfc_en_esta) > 1)

                numberTenderers = tender.get('numberOfTenderers', 0)
                soborno = (numberTenderers == 1 and count_contratos > 2)

                usoIndebidoInfo = (procurementMethod.lower() in ['selective'] and len(rfc_en_esta)>0)

                records_empresas.append({
                    'rfcEmpresa': rfc_en_esta[0],
                    'nombreEmpresa': empresa_nombre,
                    'count': count_contratos,
                    'cohecho': cohecho,
                    'desvio': desvio,
                    'conflictoInteres': conflictoInteres,
                    'soborno': soborno,
                    'usoIndebidoInfo': usoIndebidoInfo
                })

        if not records_empresas:
            data = {'total_empresas':0, 'empresas':[]}
            cache.set(cache_key, data, timeout=86400)
            return render(request, 'burbujas/filtros_dinamicos.html', {
                'data': json.dumps(data)
            })

        df_final = pd.DataFrame(records_empresas)
        df_final = df_final.groupby(['rfcEmpresa','nombreEmpresa'], as_index=False).agg({
            'count':'sum',
            'cohecho':'max',
            'desvio':'max',
            'conflictoInteres':'max',
            'soborno':'max',
            'usoIndebidoInfo':'max'
        })

        total_empresas = len(df_final)
        empresas_list = df_final.to_dict('records')

        data = {
            'total_empresas': total_empresas,
            'empresas': empresas_list
        }

        cache.set(cache_key, data, timeout=86400)

    return render(request, 'burbujas/filtros_dinamicos.html', {
        'data': json.dumps(data) # Importante: serializar a JSON
    })
