from validation.registry import INDICATORS
from validation.reference import LOADERS


def test_every_indicator_has_an_implemented_loader():
    for ind, cfg in INDICATORS.items():
        assert cfg["reference"] in LOADERS, (
            f"{ind} references loader '{cfg['reference']}' which is not in reference.LOADERS"
        )
