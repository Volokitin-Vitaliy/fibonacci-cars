"""Text search over the catalog: every word must match the make, model or year."""

from django.db.models import Q

# Russian spellings people type for popular makes and nicknames.
ALIASES = {
    'мерседес': 'mercedes', 'мерс': 'mercedes', 'бмв': 'bmw', 'ауди': 'audi',
    'порше': 'porsche', 'порш': 'porsche', 'феррари': 'ferrari', 'ферари': 'ferrari',
    'ламборгини': 'lamborghini', 'ламба': 'lamborghini', 'бентли': 'bentley',
    'роллс': 'rolls', 'ройс': 'royce', 'майбах': 'maybach', 'макларен': 'mclaren',
    'бугатти': 'bugatti', 'астон': 'aston', 'мартин': 'martin', 'рендж': 'range',
    'ровер': 'rover', 'лексус': 'lexus', 'тойота': 'toyota', 'гелик': 'g ',
    'гелендваген': 'g ', 'кайен': 'cayenne', 'урус': 'urus', 'куллинан': 'cullinan',
    'дукати': 'ducati', 'тесла': 'tesla', 'брабус': 'brabus', 'мансори': 'mansory',
}
MAX_WORDS = 6


def words(query):
    return [w for w in (query or '').lower().split() if w][:MAX_WORDS]


def search(queryset, query):
    for word in words(query):
        word = ALIASES.get(word, word).strip() or word
        condition = Q(make__name__icontains=word) | Q(model__icontains=word)
        if word.isdigit() and len(word) == 4:
            condition |= Q(year=int(word))
        queryset = queryset.filter(condition)
    return queryset
