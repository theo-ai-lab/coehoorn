from coehoorn.personas import generate_personas_heuristic
from coehoorn.schemas import Archetype


def test_heuristic_returns_n_personas_with_valid_ids():
    personas = generate_personas_heuristic(n=6)
    assert len(personas) == 6
    assert [p.id for p in personas] == ["p00", "p01", "p02", "p03", "p04", "p05"]


def test_heuristic_cycles_through_all_six_archetypes():
    personas = generate_personas_heuristic(n=6)
    assert {p.archetype for p in personas} == set(Archetype)


def test_heuristic_larger_n_produces_pool_variety_not_duplicates():
    personas = generate_personas_heuristic(n=12)
    # 12 personas across 6 archetypes means 2 of each; the two should differ.
    by_arch: dict[Archetype, list[str]] = {}
    for p in personas:
        by_arch.setdefault(p.archetype, []).append(p.name)
    for arch, names in by_arch.items():
        assert len(set(names)) == len(names), (
            f"archetype {arch} produced duplicate persona names: {names}"
        )


def test_heuristic_n_zero_returns_empty_list():
    assert generate_personas_heuristic(n=0) == []
