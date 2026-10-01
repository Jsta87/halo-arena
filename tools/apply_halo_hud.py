#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
p = root / "code/cgame/cg_draw.c"

if not p.exists():
    raise SystemExit("Run from the Halo Arena/ioquake3 source root.")

s = p.read_text()

func = r'''
/*
=====================
CG_DrawHaloShield

Temporary Halo Arena debug HUD. This will be replaced by the imported
Halo-style HUD once the asset pipeline is working.
=====================
*/
static void CG_DrawHaloShield( void ) {
	int shield;
	float frac;
	char text[32];
	vec4_t background = { 0.0f, 0.0f, 0.0f, 0.55f };
	vec4_t shieldColor = { 0.20f, 0.70f, 1.0f, 0.90f };

	if ( !cg.snap ) {
		return;
	}

	shield = cg.snap->ps.stats[STAT_SHIELD];

	if ( shield < 0 ) {
		shield = 0;
	} else if ( shield > 100 ) {
		shield = 100;
	}

	frac = (float)shield / 100.0f;

	Com_sprintf( text, sizeof(text), "SHIELD %3d", shield );
	CG_DrawSmallString( 420, 8, text, 1.0f );

	CG_FillRect( 420, 22, 200, 18, background );
	CG_FillRect( 424, 26, 192 * frac, 10, shieldColor );
}

'''

anchor = 'static void CG_Draw2D(stereoFrame_t stereoFrame)\n{'
if 'static void CG_DrawHaloShield( void )' not in s:
    if anchor not in s:
        raise SystemExit("[fail] CG_Draw2D anchor not found")
    s = s.replace(anchor, func + anchor, 1)
    print("[ok] added CG_DrawHaloShield")
else:
    print("[skip] CG_DrawHaloShield already present")

call_anchor = '''#else
			CG_DrawStatusBar();
#endif
      
			CG_DrawAmmoWarning();
'''
call_repl = '''#else
			CG_DrawStatusBar();
#endif

			CG_DrawHaloShield();
      
			CG_DrawAmmoWarning();
'''

if 'CG_DrawHaloShield();' not in s:
    if call_anchor not in s:
        raise SystemExit("[fail] HUD call anchor not found")
    s = s.replace(call_anchor, call_repl, 1)
    print("[ok] hooked shield HUD into CG_Draw2D")
else:
    print("[skip] shield HUD hook already present")

p.write_text(s)
print("\nHalo shield debug HUD applied.")
