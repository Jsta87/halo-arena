#ifndef G_HALO_SHIELD_H
#define G_HALO_SHIELD_H

#define HALO_SHIELD_MAX                100.0f
#define HALO_SHIELD_RECHARGE_DELAY_MS 5000
#define HALO_SHIELD_RECHARGE_PER_SEC    25.0f

void Halo_ShieldReset( gentity_t *ent );
int  Halo_ShieldAbsorbDamage( gentity_t *ent, int damage, int dflags );
void Halo_ShieldThink( gentity_t *ent );

#endif
