"""All makes offered in the catalog and the listing form (a broad list like the big
classifieds), and which of them have a logo in assets/img/makes/.

Logos: Simple Icons (https://simpleicons.org), CC0 1.0. The names and logos are
trademarks of their owners and are shown only to identify the make.
"""

import re
import unicodedata

MAKES = [
    'Abarth', 'Acura', 'Aixam', 'Alfa Romeo', 'Alpina', 'Alpine', 'Aston Martin', 'Audi', 'Aurus',
    'Austin', 'BAIC', 'Bentley', 'BMW', 'Borgward', 'Brabus', 'Brilliance', 'Bugatti', 'Buick', 'BYD',
    'Cadillac', 'Caterham', 'Changan', 'Chery', 'Chevrolet', 'Chrysler', 'Citroen', 'Cupra',
    'Dacia', 'Daewoo', 'DAF', 'Daihatsu', 'Datsun', 'Dodge', 'Dongfeng', 'DS', 'Ducati',
    'Exeed', 'FAW', 'Ferrari', 'Fiat', 'Fisker', 'Ford', 'Foton', 'GAC', 'Geely', 'Genesis', 'GMC',
    'Great Wall', 'Haval', 'Hino', 'Holden', 'Honda', 'Hongqi', 'Hummer', 'Hymer', 'Hyundai',
    'Ineos', 'Infiniti', 'Isuzu', 'Iveco', 'JAC', 'Jaguar', 'Jeep', 'Jetour', 'Kia', 'Koenigsegg',
    'KTM', 'Lada', 'Lamborghini', 'Lancia', 'Land Rover', 'Leapmotor', 'Lexus', 'Li Auto', 'Lincoln',
    'Lotus', 'Lucid', 'Lynk & Co', 'Mahindra', 'MAN', 'Mansory', 'Maserati', 'Maybach', 'Mazda',
    'McLaren', 'Mercedes-Benz', 'Mercury', 'MG', 'Mini', 'Mitsubishi', 'Morgan', 'Moskvich', 'Nio',
    'Nissan', 'Oldsmobile', 'Opel', 'Ora', 'Pagani', 'Peugeot', 'Pininfarina', 'Plymouth', 'Polestar',
    'Pontiac', 'Porsche', 'Proton', 'RAM', 'Ravon', 'Renault', 'Rimac', 'Rivian', 'Rolls-Royce',
    'Rover', 'Saab', 'Saturn', 'Scania', 'Scion', 'Seat', 'Skoda', 'Smart', 'SsangYong', 'Subaru',
    'Suzuki', 'Tata', 'Tesla', 'Tijhof', 'Toyota', 'TVR', 'UAZ', 'Vauxhall', 'VinFast', 'Volkswagen',
    'Volvo', 'Voyah', 'Wey', 'Xpeng', 'ZAZ', 'Zeekr', 'ГАЗ', 'ВАЗ',
]

# File names in assets/img/makes/ (without .svg); others get a generic car icon.
LOGOS = {
    'acura', 'alfaromeo', 'astonmartin', 'audi', 'bentley', 'bmw', 'bugatti', 'cadillac', 'chevrolet',
    'chrysler', 'citroen', 'dacia', 'daf', 'ferrari', 'fiat', 'ford', 'honda', 'hyundai', 'infiniti',
    'iveco', 'jaguar', 'jeep', 'kia', 'koenigsegg', 'lada', 'lamborghini', 'landrover', 'lucid',
    'mahindra', 'man', 'maserati', 'mazda', 'mclaren', 'mercedes', 'mg', 'mini', 'mitsubishi',
    'nissan', 'opel', 'peugeot', 'polestar', 'porsche', 'proton', 'ram', 'renault', 'rollsroyce',
    'saturn', 'scania', 'seat', 'skoda', 'smart', 'subaru', 'suzuki', 'tata', 'tesla', 'toyota',
    'vauxhall', 'volkswagen', 'volvo',
}
ALIASES = {'mercedesbenz': 'mercedes', 'maybach': 'mercedes', 'ваз': 'lada'}


def normalize(name):
    """'Citroën' -> 'citroen', 'Mercedes-Benz' -> 'mercedesbenz' (to compare names)."""
    text = unicodedata.normalize('NFKD', name or '')
    text = ''.join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r'[^0-9a-zа-я]', '', text)


def logo_key(name):
    key = normalize(name)
    key = ALIASES.get(key, key)
    return key if key in LOGOS else None
