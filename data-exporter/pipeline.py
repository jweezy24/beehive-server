import binascii
import logging
import re
import struct
from waggle.coresense.utils import decode_frame as decode_frame_v3
from waggle.protocol.v5.decoder import decode_frame as decode_frame_v5
from waggle.protocol.v5.decoder import convert as convert_v5


logger = logging.getLogger('pipeline')
logger.setLevel(logging.INFO)


def normalize_key(k):
    return re.sub('[-_.]+', '_', k).lower()


def normalize_value(v):
    if isinstance(v, dict):
        return {normalize_key(k2): normalize_value(v2) for k2, v2 in v.items()}
    if isinstance(v, list):
        return [normalize_value(v2) for v2 in v]
    if isinstance(v, float):
        return round(v, 3)
    return v


def trim_python_repr(s):
    if s.startswith("b'"):
        return s[2:-1]
    return s


def trim_coresense_packet(source):
    start = source.index(b'\xaa')
    end = source.rindex(b'\x55')
    return source[start:end + 1]


def reunpack_if_needed(source):
    if source[0] != 0xaa:
        return binascii.unhexlify(source.decode())
    return source


def decode_coresense_3(source):
    source = trim_coresense_packet(source)
    source = reunpack_if_needed(source)
    return decode_frame_v3(source)


def decode_coresense_4(source):
    source = trim_coresense_packet(source)
    source = reunpack_if_needed(source)

    unpacked_data = decode_frame_v5(source)

    results = {}

    for sensor_id, sensor_data in unpacked_data.items():
        for key, value in sensor_data.items():
            results[key] = {'raw': value}

    for sensor_id, sensor_data in unpacked_data.items():
        try:
            for key, (value, unit) in convert_v5(sensor_data, sensor_id).items():
                if unit == 'raw':
                    results[key] = {'raw': value}
                elif key.startswith('chemsense_at') or key.startswith('chemsense_sh') or key.startswith('chemsense_lp'):
                    results[key] = {'raw': int(value * 100), 'hrf': value, 'hrf_units': unit}
                else:
                    if key not in results:
                        results[key] = {}
                    results[key]['hrf'] = value
                    results[key]['hrf_units'] = unit
        except Exception:
            logger.exception('failed to decode {}'.format(source))

    return map_readings_4to3(results)


def decode18(data):
    bincounts = struct.unpack_from('<16H', data, offset=0)
    mtof = [x / 3 for x in struct.unpack_from('<4B', data, offset=32)]
    pmvalues = sorted(struct.unpack_from('<3f', data, offset=50))

    values = {
        'bins': bincounts,
        'mtof': mtof,
        'pm': {'1': pmvalues[0], '2.5': pmvalues[1], '10': pmvalues[2]},
    }

    return values


def decode_alphasense_1(source):
    return decode18(source)


decoders = {
    'coresense:3': decode_coresense_3,
    'coresense:4': decode_coresense_4,
    'status:0': decode_coresense_4,
    'image_example:0': decode_coresense_4,
}


def decode(row):
    plugin = ':'.join([row.plugin_name, row.plugin_version])

    source = binascii.unhexlify(trim_python_repr(row.data))

    if plugin not in decoders:
        return {}

    return decoders[plugin](source)


template_4to3 = {
    'APDS-9006-020': {
        'intensity': 'lightsense_apds_9006_020_light'
    },
    'BMP180': {
        'pressure': 'metsense_bmp180_pressure',
        'temperature': 'metsense_bmp180_temperature',
    },
    'HIH4030': {
        'humidity': 'metsense_hih4030_humidity',
    },
    'HIH6130': {
        'humidity': 'lightsense_hih6130_humidity',
        'temperature': 'lightsense_hih6130_temperature',
    },
    'HMC5883L': {
        'magnetic_field.x': 'lightsense_hmc5883l_hx',
        'magnetic_field.y': 'lightsense_hmc5883l_hy',
        'magnetic_field.z': 'lightsense_hmc5883l_hz',
    },
    'HTU21D': {
        'humidity': 'metsense_htu21d_humidity',
        'temperature': 'metsense_htu21d_temperature',
    },
    'LPS25H': {
        'pressure': 'chemsense_lpp',
        'temperature': 'chemsense_lpt',
    },
    'ML8511': {
        'intensity': 'lightsense_ml8511',
    },
    'MLX75305': {
        'intensity': 'lightsense_mlx75305',
    },
    'MMA8452Q': {
        'acceleration.x': 'metsense_mma8452q_acc_x',
        'acceleration.y': 'metsense_mma8452q_acc_y',
        'acceleration.z': 'metsense_mma8452q_acc_z',
    },
    'SHT25': {
        'humidity': 'chemsense_shh',
        'temperature': 'chemsense_sht',
    },
    'Si1145': {
        'ir_count': 'chemsense_sir',
        'uv_count': 'chemsense_suv',
        'visible_light_count': 'chemsense_svl',
    },
    'TMP421': {
        'temperature': 'lightsense_tmp421',
    },
    'TSL250RD-LS': {
        'intensity': 'lightsense_tsl250_light',
    },
    'TSL260RD': {
        'intensity': 'lightsense_tsl260_light',
    },
    'Coresense ID': {
        'mac_address': 'metsense_id',
    },
    'PR103J2': {
        'temperature': 'metsense_pr103j2_temperature',
    },
    'SPV1840LR5H-B': {
        'intensity': 'metsense_spv1840lr5h-b',
    },
    'TMP112': {
        'temperature': 'metsense_tmp112',
    },
    'TSL250RD-AS': {
        'intensity': 'metsense_tsl250rd_light',
    },
    'TSYS01': {
        'temperature': 'metsense_tsys01_temperature',
    },
    'Chemsense ID': {
        'mac_address': 'chemsense_id',
    },
    'Chemsense': {
        'co': 'chemsense_cmo',
        'h2s': 'chemsense_h2s',
        'no2': 'chemsense_no2',
        'o3': 'chemsense_ozo',
        'so2': 'chemsense_so2',
        'reducing_gases': 'chemsense_irr',
        'oxidizing_gases': 'chemsense_iaq',
        'at0': 'chemsense_at0',
        'at1': 'chemsense_at1',
        'at2': 'chemsense_at2',
        'at3': 'chemsense_at3',
    },
    'Alphasense': {
        'pm1': 'alphasense_pm1',
        'pm2.5': 'alphasense_pm2.5',
        'pm10': 'alphasense_pm10',
        'bins': 'alphasense_bins',
        'sample flow rate': 'alphasense_sample_flow_rate',
        'sampling period': 'alphasense_sampling_period',
        'id': 'alpha_serial',
        'fw': 'alpha_firmware',
    },
    'PMS7003': {
        '10um_particle': 'pms7003_10um_particle',
        '1um_particle': 'pms7003_1um_particle',
        '2_5um_particle': 'pms7003_2_5um_particle',
        '5um_particle': 'pms7003_5um_particle',
        'pm10_atm': 'pms7003_pm10_atm',
        'pm10_cf1': 'pms7003_pm10_cf1',
        'pm1_atm': 'pms7003_pm1_atm',
        'pm1_cf1': 'pms7003_pm1_cf1',
        'pm25_atm': 'pms7003_pm25_atm',
        'pm25_cf1': 'pms7003_pm25_cf1',
        'point_3um_particle': 'pms7003_point_3um_particle',
        'point_5um_particle': 'pms7003_point_5um_particle',
    },
    'net_broadband': {
        'rx': 'net_broadband_rx',
        'tx': 'net_broadband_tx',
    },
    'net_lan': {
        'rx': 'net_lan_rx',
        'tx': 'net_lan_tx',
    },
    'net_usb': {
        'rx': 'net_usb_rx',
        'tx': 'net_usb_tx',
    },
    'nc': {
        'uptime': 'nc_uptime',
        'idletime': 'nc_idletime',
        'load_1': 'nc_load_1',
        'load_5': 'nc_load_5',
        'load_10': 'nc_load_10',
        'mem_total': 'nc_ram_total',
        'mem_free': 'nc_ram_free',
    },
    'ep': {
        'uptime': 'ep_uptime',
        'idletime': 'ep_idletime',
        'load_1': 'ep_load_1',
        'load_5': 'ep_load_5',
        'load_10': 'ep_load_10',
        'mem_total': 'ep_ram_total',
        'mem_free': 'ep_ram_free',
    },
    'wagman': {
        'uptime': 'wagman_uptime',

        'boot_count': 'wagman_boot_count',

        'current_wagman': 'wagman_current_wagman',
        'current_nc': 'wagman_current_nc',
        'current_ep': 'wagman_current_ep',
        'current_cs': 'wagman_current_cs',

        'fails_nc': 'wagman_failcount_nc',
        'fails_ep': 'wagman_failcount_ep',
        'fails_cs': 'wagman_failcount_cs',

        'temperature_nc_heatsink': 'wagman_temperature_ncheatsink',
        'temperature_ep_heatsink': 'wagman_temperature_epheatsink',
        'temperature_battery': 'wagman_temperature_battery',
        'temperature_brainplate': 'wagman_temperature_brainplate',
        'temperature_powersupply': 'wagman_temperature_powersupply',

        # 'boot_flags': 'wagman_boot_flag',
        # 'nc_bootloader_flags': 'wagman_bootloader_nc_flag',

        'htu21d_temperature': 'wagman_htu21d_temperature',
        'htu21d_humidity': 'wagman_htu21d_humidity',
        # 'hih4030_humidity': 'wagman_hih4030_humidity',
        # 'light': 'wagman_light',

        'enabled_nc': 'wagman_enabled_nc',
        'enabled_ep': 'wagman_enabled_ep',
        'enabled_cs': 'wagman_enabled_cs',

        'heartbeat_nc': 'wagman_heartbeat_nc',
        'heartbeat_ep': 'wagman_heartbeat_ep',
        'heartbeat_cs': 'wagman_heartbeat_cs',
    },
    'image_example': {
        'device': 'image_device',
        'average_color_r': 'image_average_color_r',
        'average_color_g': 'image_average_color_g',
        'average_color_b': 'image_average_color_b',
        'histogram_r': 'image_histogram_r',
        'histogram_g': 'image_histogram_g',
        'histogram_b': 'image_histogram_b',
    }
}


def stringify(x):
    if x is None:
        return ''
    if isinstance(x, tuple) or isinstance(x, list):
        return ','.join([stringify(xi) for xi in x])
    if isinstance(x, bytes) or isinstance(x, bytearray):
        return binascii.hexlify(x).decode()
    return str(x)


def map_parameters_4to3(readings, parameters):
    output = {}

    for p, k in parameters.items():
        try:
            output[p] = readings[k]
        except KeyError:
            continue

    return output


def map_readings_4to3(readings):
    output = {}

    for sensor, parameters in template_4to3.items():
        output[sensor] = map_parameters_4to3(readings, parameters)

    return output
