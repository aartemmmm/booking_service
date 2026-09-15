"""
Router: по значению ключа шардирования определяет, на каком шарде лежит запись.

Две стратегии:
  ModuloRouter          — shard = hash(key) % N;
  ConsistentHashRouter  — ключ и шарды отображаются в точки на кольце,
                          запись принадлежит ближайшему шарду по часовой стрелке.

Шард в обоих случаях — это имя подключения из settings.DATABASES
('shard_0', 'shard_1', ...). Router только вычисляет имя и к базе не обращается,
поэтому им можно считать размещение и для шардов, которых ещё нет.
"""

import bisect
import hashlib

# Точки на кольце — 64-битные целые: [0, 2^64)
RING_SIZE = 2 ** 64


def stable_hash(value):
    """
    Детерминированный 64-битный хеш: первые 8 байт MD5 от строкового значения.

    Встроенный hash() не подходит. Для строк он меняется при каждом запуске
    Python (PYTHONHASHSEED), и разные процессы backend отправляли бы одну и ту же
    запись на разные шарды. Для чисел hash(101) == 101, то есть «хеш» совпадает
    с самим ключом, и распределение зависело бы от порядка выдачи id.
    """
    digest = hashlib.md5(str(value).encode('utf-8')).digest()
    return int.from_bytes(digest[:8], 'big')


class ModuloRouter:
    """shard = hash(key) % N, где N — число шардов."""

    def __init__(self, shards):
        if not shards:
            raise ValueError('Нужен хотя бы один шард.')
        self.shards = list(shards)

    def shard_index(self, key):
        return stable_hash(key) % len(self.shards)

    def shard_for(self, key):
        return self.shards[self.shard_index(key)]

    def __repr__(self):
        return f'ModuloRouter(N={len(self.shards)})'


class ConsistentHashRouter:
    """
    Consistent Hash Ring.

    Каждый шард получает vnodes точек на кольце: позиция точки — hash("shard#номер").
    Ключ получает позицию hash(key) и принадлежит шарду первой точки, стоящей
    по кольцу после неё (по часовой стрелке). После самой большой точки кольцо
    замыкается на самую маленькую.

    vnodes=1 — базовое кольцо: одна точка на шард.
    vnodes>1 — virtual nodes: у каждого шарда много точек, разбросанных по кольцу.
    """

    def __init__(self, shards, vnodes=1):
        if not shards:
            raise ValueError('Нужен хотя бы один шард.')
        if vnodes < 1:
            raise ValueError('vnodes должно быть не меньше 1.')
        self.shards = list(shards)
        self.vnodes = vnodes

        points = sorted(
            (stable_hash(f'{shard}#{number}'), shard)
            for shard in self.shards
            for number in range(vnodes)
        )
        self._positions = [position for position, _ in points]
        self._owners = [shard for _, shard in points]

    def shard_for(self, key):
        position = stable_hash(key)
        # Первая точка шарда, стоящая строго после позиции ключа
        index = bisect.bisect_right(self._positions, position)
        if index == len(self._positions):
            index = 0  # прошли максимум — кольцо замыкается
        return self._owners[index]

    def ring_share(self):
        """Доля кольца, которая принадлежит каждому шарду (от 0 до 1)."""
        share = dict.fromkeys(self.shards, 0)
        count = len(self._positions)
        for i, position in enumerate(self._positions):
            previous = self._positions[i - 1] if i else self._positions[-1] - RING_SIZE
            share[self._owners[i]] += position - previous
        return {shard: arc / RING_SIZE for shard, arc in share.items()} if count else share

    def points(self):
        """Точки кольца по порядку: [(позиция, шард), ...]."""
        return list(zip(self._positions, self._owners))

    def __repr__(self):
        return f'ConsistentHashRouter(N={len(self.shards)}, vnodes={self.vnodes})'
