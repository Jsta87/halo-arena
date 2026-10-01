#include "g_local.h"
#include "g_halo_shield.h"

static void Halo_ShieldPublish( gentity_t *ent ) {
    int value;

    if ( !ent || !ent->client ) {
        return;
    }

    value = (int)( ent->client->haloShield + 0.5f );

    if ( value < 0 ) {
        value = 0;
    } else if ( value > (int)HALO_SHIELD_MAX ) {
        value = (int)HALO_SHIELD_MAX;
    }

    ent->client->ps.stats[STAT_SHIELD] = value;
}

void Halo_ShieldReset( gentity_t *ent ) {
    if ( !ent || !ent->client ) {
        return;
    }

    ent->client->haloShield = HALO_SHIELD_MAX;
    ent->client->haloShieldLastDamageTime = level.time;
    ent->client->ps.stats[STAT_ARMOR] = 0;

    Halo_ShieldPublish( ent );
}

int Halo_ShieldAbsorbDamage( gentity_t *ent, int damage, int dflags ) {
    float absorbed;

    if ( damage <= 0 || !ent || !ent->client ) {
        return damage;
    }

    if ( dflags & DAMAGE_NO_PROTECTION ) {
        return damage;
    }

    ent->client->haloShieldLastDamageTime = level.time;

    if ( ent->client->haloShield <= 0.0f ) {
        Halo_ShieldPublish( ent );
        return damage;
    }

    absorbed = (float)damage;
    if ( absorbed > ent->client->haloShield ) {
        absorbed = ent->client->haloShield;
    }

    ent->client->haloShield -= absorbed;
    if ( ent->client->haloShield < 0.0f ) {
        ent->client->haloShield = 0.0f;
    }

    Halo_ShieldPublish( ent );

    damage -= (int)absorbed;
    return damage < 0 ? 0 : damage;
}

void Halo_ShieldThink( gentity_t *ent ) {
    float deltaSeconds;

    if ( !ent || !ent->client || ent->health <= 0 ) {
        return;
    }

    if ( ent->client->sess.sessionTeam == TEAM_SPECTATOR ) {
        return;
    }

    if ( ent->client->haloShield >= HALO_SHIELD_MAX ) {
        ent->client->haloShield = HALO_SHIELD_MAX;
        Halo_ShieldPublish( ent );
        return;
    }

    if ( level.time - ent->client->haloShieldLastDamageTime <
         HALO_SHIELD_RECHARGE_DELAY_MS ) {
        Halo_ShieldPublish( ent );
        return;
    }

    deltaSeconds = (float)( level.time - level.previousTime ) / 1000.0f;
    if ( deltaSeconds <= 0.0f ) {
        return;
    }

    ent->client->haloShield += HALO_SHIELD_RECHARGE_PER_SEC * deltaSeconds;

    if ( ent->client->haloShield > HALO_SHIELD_MAX ) {
        ent->client->haloShield = HALO_SHIELD_MAX;
    }

    Halo_ShieldPublish( ent );
}
