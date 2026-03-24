from islandsim.models import (
    NationName,
    NationState,
    Relationship,
    Resources,
    WorldState,
)

STARTING_STATE = WorldState(
    turn=1,
    max_turns=8,
    nations={
        NationName.NARU: NationState(
            name=NationName.NARU,
            resources=Resources(military=45, treasury=70, food=30, support=60),
            traits=(
                "Pragmatic strait power. Controls the only two deep-water shipping "
                "channels (North and South Channel). Rich from toll revenue but "
                "critically dependent on food imports. Small population. Historically "
                "neutral and transactional."
            ),
        ),
        NationName.VELDARA: NationState(
            name=NationName.VELDARA,
            resources=Resources(military=30, treasury=55, food=75, support=50),
            traits=(
                "Largest island, resource giant. Rich mineral deposits (rare earths), "
                "fertile farmland, largest population. Weak navy. Needs Naru Strait "
                "for exports. Internal tension between mining and farming interests. "
                "Confident, sometimes overreaching. Sees itself as natural regional leader."
            ),
        ),
        NationName.TAUMA: NationState(
            name=NationName.TAUMA,
            resources=Resources(military=65, treasury=40, food=35, support=55),
            traits=(
                "Naval power. Archipelago with deep harbors and strong maritime "
                "tradition. Best navy in the region. Limited resources beyond fish, "
                "no rare earths, poor farming soil. Depends on Veldara for minerals "
                "and goods transiting through Naru Strait. Proud, independent, "
                "suspicious of Veldara's ambitions."
            ),
        ),
    },
    relationships=[
        Relationship(nation_a=NationName.NARU, nation_b=NationName.VELDARA, sentiment=10),
        Relationship(nation_a=NationName.NARU, nation_b=NationName.TAUMA, sentiment=5),
        Relationship(nation_a=NationName.VELDARA, nation_b=NationName.TAUMA, sentiment=-10),
    ],
    reef_maru_status=(
        "Unclaimed. A massive rare earth deposit has just been discovered on Reef Maru, "
        "a small uninhabited atoll in disputed waters where all three nations' sovereignty "
        "claims overlap. The deposit is estimated to be worth more than Veldara's entire "
        "existing reserves."
    ),
    active_effects=["Severe typhoon season forecast — expected to threaten shipping routes and food supplies"],
    strait_open=True,
)

ECONOMIC_RULES = """\
Each turn, the following automatic economic adjustments occur:

Treasury income (if trade routes are functional):
- Naru: +10 (toll revenue from strait shipping)
- Veldara: +8 (mining exports, requires strait access)
- Tauma: +5 (fishing economy)

Food production:
- Naru: +3 (limited farmland)
- Veldara: +8 (fertile lowlands)
- Tauma: +5 (fishing)

Food consumption: -5 per turn for all nations.

If the Naru Strait is blockaded:
- Naru loses toll income
- Veldara cannot export minerals (loses treasury income)
- Tauma cannot import minerals/goods from Veldara

Critical thresholds:
- Food below 20: domestic unrest, -5 Support per turn
- Food below 10: crisis, -10 Support per turn, risk of government collapse
- Support below 25: government instability, erratic behavior
"""

ACTION_MENU = """\
Common actions with approximate resource costs:

MILITARY:
- Deploy naval patrol to Reef Maru: -10 Military, -5 Treasury
- Establish military base on Reef Maru: -20 Military, -15 Treasury (takes 2 turns)
- Naval blockade of strait or port: -15 Military/turn, diplomatic fallout
- Defensive posture (fortify home waters): -5 Military, +5 Support

ECONOMIC:
- Propose trade deal (bilateral): variable Treasury, negotiated terms
- Impose trade sanctions: -5 Treasury (lost trade), target loses more
- Invest in infrastructure: -15 Treasury now, +income in future turns
- Economic aid to another nation: -10 Treasury, +10 target's Support toward you

DIPLOMATIC:
- Public declaration of sovereignty over Reef Maru: +5 Support, -relations with others
- Propose joint development agreement: requires negotiation
- Secret back-channel negotiation: risk of detection
- Appeal to international community: slow but legitimizing, +5 Support
- Espionage: -5 Treasury, chance of discovering secrets, chance of getting caught

DOMESTIC:
- Ration food supplies: slows Food decline, -5 Support
- Propaganda campaign: -5 Treasury, +10 Support (diminishing returns)
- Emergency food imports: -15 Treasury, +15 Food (if trade routes open)

Nations can attempt any plausible action — this menu is non-exhaustive.
"""
