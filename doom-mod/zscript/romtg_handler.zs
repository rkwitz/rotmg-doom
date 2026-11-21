// ROMTG-Doom: the realm in Doom. The swapper (scripts/duo.py) sends what the RotMG client sees,
// already in Doom units around a moving origin, one line each over RomtgBridge
// (port-patches/0001):
//
//   clear                              everything goes (new map, or the link came back)
//   f ID X Y SPRITE SCALE              a ground tile: a flat sprite on the floor
//   w ID X Y SIZE SPRITE TOP SCALE [HEIGHT]
//                                      a wall: a box of SIZE (HEIGHT high, if not SIZE) with
//                                      SPRITE sides and TOP ("-": none); also RotMG's 3D objects
//   b ID X Y Z SPRITE SCALE            a decoration (tree, rock...): an upright sprite
//   mv ID X Y Z                        something that moves (enemy, player, projectile) moved
//   d ID                               ID is gone (out of sight, or removed in RotMG)
//   weapon SPRITE PX                   the RotMG weapon you hold ("-": none), drawn in your hand
//   scale S EYE                        a tile is S units; your eyes are EYE units up
//   quest X Y HP MAX NAME | quest -    the boss/quest RotMG points you to: bar and direction
//   cash GOLD FAME                     your gold and fame
//   st COLOR TEXT                      a status text over you in RotMG (XP gained, level up...)
//   chat NC TC NAME<tab>TO<tab>TEXT    a chat line
//   fc ID X Y RGB SCALE [Z]            ground past RotMG's sight, in its minimap colour
//   hp ID HP MAX                       an enemy's health: a bar at its feet (a sprite, so walls
//                                      and objects in front hide it as they hide the enemy)
//   ds ID COLOR TEXT                   a status text over thing ID in RotMG (damage numbers)
//   fx ID KIND RGB                     RotMG's particles on thing ID: "fountain" (the nexus
//                                      fountains' water, shooting up and falling, in RGB)
//   bgt SPRITE                         the most common ground round you: a faint copy of it
//                                      covers the floor past the far ground
//   atk MS                             your weapon went off; the next shot is MS away (its rate
//                                      of fire): the weapon in your hand kicks over that time
//   bg RGB                             the colour round you: RotMG's ground nearby, on average.
//                                      Doom's floor, horizon and (darker) sky take it, and the
//                                      far ground (fc) fades into it towards the edge of sight
//   panel 1|0                          Tab: RotMG's side panel has the mouse; Doom greys out
// RotMG's own HUD (boss bar, gold and fame, chat, status texts) is drawn by RotMG itself in a
// see-through window over Doom (romtg/HudWindow.as); here only what needs Doom's 3D view.
//   ctl 1|0                            Doom has the controls (and walks you: Walk) or RotMG does
//   spd U                              your walking speed now, units a second
//   grid X Y R CELLS                   the squares round you for walking (see Walk, Valid)
//   (Doom sends `goto X Y`: where it has walked you, for RotMG to follow)
//   p X Y [MS]                         where your RotMG character is (MS: when, the client's clock;
//                                      replayed at an even pace, see Replay)
//   shift DX DY                        the origin moved: everything moves by DX, DY
//
// Doom sends back the way you want to walk, `m X Y` (a Doom-world vector of length 0 or 1), and
// RotMG walks your character there at its own speed; and `fire 1|0 ANGLE`, whether you hold fire
// and where you look, and RotMG shoots your own weapon that way at its own rate. Doom never moves the player itself
// (RomtgPlayer has no speed): its position always comes from RotMG.
class RomtgHandler : StaticEventHandler
{
	const MAX_LINES_PER_TIC = 20000;
	const RESEND_TICS = 10;
	const THROW_PITCH_NEAR = 35.0;   // looking this far down: a throw lands at your feet
	const THROW_PITCH_FAR = -25.0;   // looking this far up: as far as it goes
	const SELF_BAR_WIDTH = 0.94;     // third person: the green of your bar against your picture's width (1.0 too wide, 0.88 narrow; Ryan)
	const SELF_BAR_GAP = 0.1;        // ...its top this much of your picture's height below your feet (RotMG: 4 px under 40)
	const CAM_DIST_TILES = 4.5;      // third person: the camera this far back along your look
	const CAM_PITCH = 15.0;          // ...looking down at you at this angle, fixed: low, behind you (Ryan, 2026-11-20)
	const CAM_PITCH_MIN = 15.0;      // the mouse's up and down then only aims throws, between
	const CAM_PITCH_MAX = 80.0;      // ...these

	Array<Actor> things;
	Vector2 lastMove;
	int lastMoveAt;
	int lastFire, lastAim, lastFireAt;
	// A thrown ability aimed with Space held (`throwaim 1 MAX RADIUS`, Doom units): how far it
	// goes follows your look up and down, sent as `throw D`; DrawThrowArc shows where it lands.
	// Third person (`cam 1`, C or RotMG's camera button; Ryan 2026-11-20): the camera behind and
	// above you, looking down at your own character, which the bridge then sends as a thing like
	// any other (`selfid` says which), kept on Doom's player here.
	bool thirdPerson, camSet, selfBack;
	Map<String, String> spriteMask;   // sprite lump -> "W H HEX": its solid pixels (romtgmsk.txt, assets.py sprite_masks)
	double selfWidth, selfHeight;        // how wide your character is drawn (Doom units): your bar's width in third person
	int selfId;
	double throwPitch;      // third person: the look up and down the mouse makes, for throws only
	Vector2 selfWas;
	double pitchMin, pitchMax;   // Doom's own look limits, put back after third person
	bool throwAim;
	double throwMax, throwRadius, throwSent;
	int throwSentAt;
	string weaponSprite;
	bool weaponFlip;
	string weaponFrame;
	int weaponPx;

	// RotMG's HUD, for RenderOverlay.
	const CHAT_LINES = 9;
	const CHAT_TICS = 35 * 25;
	const STATUS_TICS = 35 * 2;
	bool hasQuest;
	Vector2 questPos;
	int questHp, questMax;
	string questName;
	int gold, fame;
	Array<string> chatText;
	Array<int> chatColor, chatNameColor, chatAt;
	Array<string> chatName;
	Array<string> statusText;
	Array<int> statusColor, statusAt;
	double eye;
	Array<int> thingHp, thingMax;   // enemies' health, by thing id (0 max: no bar)
	Array<Actor> bars;              // their health bars, by thing id
	Array<int> barIds;              // the ids that have one
	bool panel;                     // Tab: RotMG's side panel has the mouse
	bool modalUp;                   // `modal`: a RotMG dialog is open over Doom (dimmed behind it)
	// Status texts over things (damage numbers), for RenderOverlay.
	Array<int> floatColor, floatAt;
	Array<string> floatText;
	const DAMAGE_TILES = 12;   // RotMG's screen reaches about this far from you (ds)
	// What each text is over, while it's there, and where (its head) as last seen: a text
	// stays where its enemy died. (By id they followed whatever took the id next, a
	// projectile, 2026-11-12.)
	Array<Actor> floatThing;
	Array<double> floatX, floatY, floatZ;
	const FLOAT_TICS = 35;          // RotMG's damage numbers rise and go in a second
	// The ground: drawn into Doom's real floor (a canvas texture, RTGROUND, on the map's one
	// sector), not as sprites. Doom pulls every sprite a little towards the camera, ground
	// tiles included, so flat ground sprites covered the feet of anything standing on them
	// (2026-11-12). The floor is real geometry: nothing standing on it is ever covered.
	// By thing id: 0 nothing, 1 a ground tile (its picture), 2 far ground (a colour),
	// 3 a far wall/tree (a colour, over the ground).
	Array<int> gKind, gColor;
	Array<int> gAnim;               // 0 still, 1 flowing, 2 rocking (fa): moving water, lava...
	Array<double> gDx, gDy;
	int animLogged;
	bool sinking;                   // standing in water (sink): your eyes go down, as RotMG sinks you
	double sunk;                    // 0..1, eased
	Array<double> gX, gY;
	Array<string> gSprite;
	int groundVersion;              // bumped on every change; the canvas is redrawn when it moves
	ui int drawnGround;
	int bgColor;
	// On a shift (the origin re-centring) the floor's texture is panned with the world, in the
	// same instant, instead of redrawn: the redraw shows a frame late, and for that frame the
	// ground stood 24 tiles off (the flicker that stayed, 2026-11-12). Offsets from
	// hw_SetPlaneTextureRotation: column = scale * (x + xoffs), canvas row = -scale * (y - yoffs).
	double panX, panY;
	string bgSprite;
	const PATTERN_TILES = 44;       // the faint ground pattern reaches this far (past FADE_TO)
	const PATTERN_ALPHA = 0.3;
	int atkAt, atkTics;             // your last shot, and the time to the next (atk)
	int atkMs;                      // ...that time in ms, for your attack frames in third person
	int weaponSlot;                 // RotMG's SlotType: sword 1, dagger 2, bow 3, wand 8, staff 17, katana 24
	// RTGROUND's size (ANIMDEFS): 256 tiles of 16 pixels, wrapping. 16, not RotMG's 8, so
	// moving water slides in half-pixel steps (at 8 it stepped a couple of times a second).
	const GROUND_PX = 4096;
	const CELL_PX = 16;
	// Particle effects (fx), by the thing they're on.
	Array<Actor> fxThing;
	// Your path as the client reported it (its clock, ms; Doom x, y), replayed REPLAY_DELAY ms
	// behind at exactly one tic's worth of time a tic. RotMG reports at its frame rate (60) and
	// Doom ticks at 35: jumping to the latest place each tic moved you one frame's step, then
	// two, then one: the stutter at 300 fps (Ryan, 2026-11-15).
	Array<double> pathT, pathX, pathY;
	double replayT;
	bool replaying;
	// Just over one report (RotMG reports every ~17 ms): less delay felt sluggish to start and
	// stop (45 ms, Ryan 2026-11-15).
	// The delay follows how often reports come (RotMG's frame rate): a little over one report
	// interval, between REPLAY_MIN and REPLAY_MAX ms.
	const REPLAY_MIN = 8.0;
	const REPLAY_MAX = 25.0;
	double reportEvery;             // ms between reports, smoothed
	const REPLAY_GAP = 60.0;        // reports further apart than this: you had stopped
	const TIC_MS = 1000.0 / 35.0;
	// Doom walks you (Ryan, 2026-11-15: Doom decides where you are). While it has the controls
	// (`ctl 1`) and knows your speed (`spd`, units/s), each tic it moves you at once against the
	// squares round you (`grid`, read as RotMG's Player.isValidPosition reads them) and sends
	// `goto`; RotMG follows at its own speed and walls, and its reports (`p`) only pull you back
	// if it couldn't follow (LEAD_*).
	bool control;
	double walkSpeed;
	Vector2 walkPush;               // a conveyor's push under you, units a second (`push`)
	// Your status effects (`cond`, RotMG's two condition words): blind, drunk, paused are
	// drawn (StatusShaders), confused swaps your keys (InputDir), as RotMG's client does.
	int cond0, cond1;
	const COND_BLIND = 1 << 7;
	const COND_HALLUCINATING = 1 << 8;
	const COND_DRUNK = 1 << 9;
	const COND_CONFUSED = 1 << 10;
	const COND_PAUSED = 1 << 20;
	ui int shadersOn;               // which of them are on now
	Array<int> gridCells;
	int gridR;
	Vector2 gridAt;                 // Doom position of the corner of the grid's middle square
	Vector2 lastGoto;
	int lastGotoAt, lastReportAt;
	const LEAD_SECONDS = 0.1;       // how far ahead of RotMG's last report you may be: this much walking...
	const LEAD_TILES = 0.15;        // ...plus this
	int walkClamps, walkBlocks, walkStatAt;   // logged (WalkStats) to find invisible walls
	double walkClampMax;
	// Stutter measurements (logged every STATS_TICS while you move).
	const STATS_TICS = 35 * 3;
	Vector2 statLast;
	double statSum, statMax, statMin;
	int statTics, statStill, statPLines, statStart;
	ui double frameLast, frameMax, groundMax, frameSince;
	ui int frames, framesSlow, groundDraws;
	// Shots' particle trails (`tr`), by thing id: colour, lifetime in tics (0: none), and the
	// share of RotMG's sparks drawn for someone else's shot (intensity; yours always).
	// Characters under Healing (`heal`), by thing id, and you: RotMG's green sparkles round them.
	Array<bool> healing;
	bool meHealing;
	// Other players' name tags (`nm`), by thing id; drawn over their heads (DrawNameTags).
	Array<string> nameText;
	Array<int> nameColor;
	// Shots pointed the way they fly (`sa`), by thing id: direction (Doom degrees), the way the
	// picture itself points (degrees, up from pointing right), its spin (ms a radian, 0: none).
	Array<double> shotYaw, shotTex, shotSpin;
	Array<bool> shotAimed;
	// Characters' animation (`an`), by thing id: action (0 stand, 1 walk, 2 attack; -1 none),
	// facing (Doom degrees), since which tic. Frames A stand, F G walk, H I attack (assets.py).
	Array<int> animAct, animSince;
	Array<int> animMs;       // ms its two frames take, as RotMG plays them (`an`'s 4th field; 0: the defaults below)
	Array<double> animYaw;
	Array<int> trailColor, trailTics;
	Array<double> trailShare;
	Array<RomtgDrop> drops;         // fountain spray in the air (moved on shifts, gone on clears)
	Array<int> fxColor;
	// The far ground (fc): faded into the background towards the edge of sight.
	Array<Actor> farTiles;
	const FADE_FROM = 50.0;         // tiles: fully drawn up to here (bridge.py's SIGHT is 48)...
	const FADE_TO = 58.0;           // ...and gone by here (bridge.py's FAR_SIGHT)
	const FADE_EVERY = 4;           // tics between fades
	// Everything in sight (enemies, shots, loot, trees, walls...) fades in over the last tiles
	// of sight instead of popping in at its edge (bridge.py's SIGHT, 48; Ryan, 2026-11-13: fog
	// ending at 48, not too deep, gradual).
	const SHOW_FADE_FROM = 36.0;    // tiles: fully drawn up to here...
	const SHOW_FADE_TO = 48.0;      // ...invisible from here
	const SHOW_FADE_EVERY = 2;      // tics between updates
	const LIFT_TILES = 0.02;
	const FOUNTAIN_HEIGHT = 0.33;   // the spray's arc against RotMG's numbers (see Fountains)
	const FOUNTAIN_SPEED = 1.8;     // and its pace: same arc, played faster (Ryan: too slow)        // upright things stand this far up (bridge.py's LIFT_TILES)

	// Every sprite's solid pixels, from romtgmsk.txt in the mod (once).
	void LoadMasks()
	{
		if (spriteMask.CountUsed() > 0)
		{
			return;
		}
		int lump = Wads.CheckNumForFullName("romtgmsk.txt");
		if (lump < 0)
		{
			return;
		}
		Array<String> lines;
		Wads.ReadLump(lump).Split(lines, "\n", TOK_SKIPEMPTY);
		for (int i = 0; i < lines.Size(); i++)
		{
			int sp = lines[i].IndexOf(" ");
			if (sp > 0)
			{
				spriteMask.Insert(lines[i].Left(sp), lines[i].Mid(sp + 1));
			}
		}
	}

	override void OnRegister()
	{
		// To the console and log only, not on screen.
		Console.PrintfEx(PRINT_HIGH | PRINT_NONOTIFY, "[romtg] doom-mod loaded");
	}

	override void WorldLoaded(WorldEvent e)
	{
		LoadMasks();
		TextureID ground = TexMan.CheckForTexture("RTGROUND", TexMan.Type_Any);
		for (int i = 0; i < level.sectors.Size(); i++)
		{
			if (ground.IsValid())
			{
				level.sectors[i].SetTexture(Sector.floor, ground);
			}
			level.sectors[i].SetSpecialColor(Sector.floor, Color(255, 255, 255, 255));
		}
		groundVersion++;
		things.Clear();
		bars.Clear();
		barIds.Clear();
		farTiles.Clear();
		lastMoveAt = -1000;
		lastFireAt = -1000;
		selfId = -1;
	}

	// Doom's whole map is one sector (scripts/flatmap.py): a white floor, far walls and ceiling,
	// coloured here, all one colour, RGB: the fog the ground fades into, the floor past it and
	// the sky, so there is no horizon to see past the end of sight (Ryan, 2026-11-13: a darker
	// sky showed a band of far floor under it).
	void SetBackground(int rgb)
	{
		if (level.sectors.Size() == 0)
		{
			return;
		}
		int r = (rgb >> 16) & 255, g = (rgb >> 8) & 255, b = rgb & 255;
		Color ground = Color(255, r, g, b);
		Color sky = ground;
		bgColor = rgb;
		groundVersion++;
		for (int i = 0; i < level.sectors.Size(); i++)
		{
			Sector s = level.sectors[i];
			s.SetSpecialColor(Sector.floor, Color(255, 255, 255, 255));   // RTGROUND has the colours
			s.SetSpecialColor(Sector.ceiling, sky);
			s.SetSpecialColor(Sector.walltop, sky);
			// The far walls all sky: their feet in the ground's colour read as more ground far
			// out past the end of sight (Ryan, 2026-11-12).
			s.SetSpecialColor(Sector.wallbottom, sky);
		}
	}

	// The far ground fades out (see-through, over the floor of the background colour) from
	// FADE_FROM to FADE_TO tiles away, so RotMG's sight ends softly, not at a black edge.
	void FadeFar(Actor mo)
	{
		if (eye <= 0)
		{
			return;
		}
		for (int i = farTiles.Size() - 1; i >= 0; i--)
		{
			Actor t = farTiles[i];
			if (t == null)
			{
				farTiles.Delete(i);
				continue;
			}
			SetFarAlpha(t, FarAlpha(t, mo));
		}
	}

	// Where you are this tic: your reported path at replayT, which runs REPLAY_DELAY ms behind
	// the newest report and moves on exactly one tic's time a tic (eased back if it drifts).
	void Replay(Actor mo)
	{
		int n = pathT.Size();
		if (n == 0)
		{
			return;
		}
		double delay = reportEvery > 0 ? clamp(reportEvery * 1.5, REPLAY_MIN, REPLAY_MAX) : REPLAY_MAX;
		double target = pathT[n - 1] - delay;
		if (!replaying || replayT < target - REPLAY_GAP)
		{
			replayT = target;   // first report, or behind (moving again after a stop): catch up at once
			replaying = true;
		}
		else
		{
			replayT += TIC_MS;
			replayT += (target - replayT) * 0.2;
		}
		// Never past the newest report: standing still, it ran on, got "too far ahead", was
		// set back and replayed the last steps again and again: you twitched back and forth
		// whenever you stopped (Ryan, 2026-11-15).
		replayT = min(replayT, pathT[n - 1]);
		Vector2 at = (pathX[n - 1], pathY[n - 1]);
		if (replayT <= pathT[0])
		{
			at = (pathX[0], pathY[0]);
		}
		else
		{
			for (int i = 0; i < n - 1; i++)
			{
				if (replayT <= pathT[i + 1])
				{
					double span = pathT[i + 1] - pathT[i];
					double f = span > 0 ? (replayT - pathT[i]) / span : 1.0;
					at = (pathX[i] + (pathX[i + 1] - pathX[i]) * f, pathY[i] + (pathY[i + 1] - pathY[i]) * f);
					break;
				}
			}
		}
		if ((at - mo.pos.xy).Length() > 0.001)
		{
			mo.SetOrigin((at.x, at.y, mo.floorz), true);
		}
	}

	// Each shot's picture turned (roll) to point where it's going on your screen: its place and
	// a step along its flight both seen from your eye, the line between them is its heading
	// there; less the way the picture itself points; plus its spin, as RotMG spins it.
	// Where Doom's view is: your eye, or in third person CAM_DIST_TILES back along your look
	// (as SetViewPos's offset, turned by your yaw and pitch, puts it). Shots are turned and
	// creatures flipped for this point, so they're right from the camera (Ryan, 2026-11-21).
	Vector3 ViewFrom(PlayerInfo p)
	{
		Vector3 from = (p.mo.pos.xy, p.viewz);
		if (!thirdPerson)
		{
			return from;
		}
		double tile = eye > 0 ? eye / (0.8 * 0.85) : 64;
		double back = tile * CAM_DIST_TILES;
		double yw = p.mo.angle, pt = p.mo.pitch;
		return from - (cos(pt) * cos(yw), cos(pt) * sin(yw), -sin(pt)) * back;
	}

	void AimShots(PlayerInfo p)
	{
		if (p.mo == null || shotAimed.Size() == 0)
		{
			return;
		}
		Vector3 eyePos = ViewFrom(p);   // the camera: your eye, or behind you in third person
		double yaw = p.mo.angle, pitch = p.mo.pitch;
		for (int i = 0; i < shotAimed.Size() && i < things.Size(); i++)
		{
			Actor t = things[i];
			if (!shotAimed[i] || t == null)
			{
				continue;
			}
			double spin = shotSpin[i] != 0 ? (level.maptime * 1000.0 / 35.0) / shotSpin[i] * 180.0 / M_PI : 0;
			if (LeanShot(t, eyePos, shotYaw[i], shotTex[i] - spin))
			{
				continue;
			}
			t.bFLATSPRITE = false;
			Vector2 a = ViewDir(t.pos - eyePos, yaw, pitch);
			Vector2 b = ViewDir(t.pos + (cos(shotYaw[i]), sin(shotYaw[i]), 0) * 16 - eyePos, yaw, pitch);
			if (a.x >= 1e8 || b.x >= 1e8)
			{
				continue;
			}
			double heading = atan2(b.y - a.y, b.x - a.x);
			t.roll = heading - shotTex[i] - spin;
		}
	}

	// A shot drawn as a card lying along its flight, turned about that line to face you as
	// much as it can (Ryan, 2026-11-16: shots flying away from or at you stood straight up on
	// screen; from the side they were right, and still are). Seen end on it shortens, but no
	// more than a little (it tilts at most SHOT_LEAN_MAX out of the screen), so it never thins
	// to nothing. TEX: which way the picture points (degrees from its right, anticlockwise),
	// its spin in. False if it can't (seen exactly end on): drawn flat on the screen instead.
	//
	// GZDoom draws a flat sprite (hw_sprites.cpp) lying flat, its right along +x and its top
	// along -y (so seen from above it's mirrored, and points at roll - TEX), then rolled (anticlockwise about z) by roll, tilted by pitch and turned to
	// angle: its face's normal is (sin pitch cos angle, sin pitch sin angle, cos pitch), and
	// its own axes E1 = (cos al, sin al, 0), E2 = (-cos pitch sin al, cos pitch cos al,
	// sin pitch) with al = angle + 90. (First written with its right along -x: shots lay
	// sideways, Ryan 2026-11-16; checked since against hw_sprites.cpp's UVs, ul = UR.)
	const SHOT_LEAN_MAX = 30;   // light: mostly facing you (Ryan chose, 2026-11-16)
	bool LeanShot(Actor t, Vector3 eyePos, double flightYaw, double tex)
	{
		Vector3 v = t.pos - eyePos;
		double vl = v.Length();
		if (vl < 1)
		{
			return false;
		}
		v /= vl;
		Vector3 d = (cos(flightYaw), sin(flightYaw), 0);
		double dv = d dot v;
		Vector3 q = d - v * dv;          // its flight as it crosses your view
		double ql = q.Length();
		if (ql < 0.02)
		{
			return false;
		}
		q /= ql;
		double lean = min(asin(clamp(abs(dv), 0, 1)), SHOT_LEAN_MAX);
		Vector3 along = q * cos(lean) + v * (dv >= 0 ? sin(lean) : -sin(lean));
		Vector3 across = (v cross q).Unit();
		Vector3 n = (along cross across).Unit();
		if (n.z < 0)
		{
			n = -n;
		}
		double tilt = acos(clamp(n.z, -1, 1));
		double turn = (abs(n.x) + abs(n.y) > 1e-6) ? atan2(n.y, n.x) : 0;
		double al = turn + 90;
		Vector3 e1 = (cos(al), sin(al), 0);
		Vector3 e2 = (-cos(tilt) * sin(al), cos(tilt) * cos(al), sin(tilt));
		double beta = atan2(along dot e2, along dot e1);
		t.bFLATSPRITE = true;
		t.angle = turn;
		t.pitch = tilt;
		t.roll = beta + tex;
		return true;
	}

	// Characters' frames as RotMG's AnimatedChar picks them: walking, the two walk frames turn
	// about (RotMG: half of a 400 ms step each), attacking, the two attack frames (half of its
	// 300 ms each), else standing; drawn facing right, mirrored when they face left on screen.
	void Animate(PlayerInfo p)
	{
		if (p.mo == null || animAct.Size() == 0)
		{
			return;
		}
		Vector3 eyePos = ViewFrom(p);
		double yaw = p.mo.angle, pitch = p.mo.pitch;
		for (int i = 0; i < animAct.Size() && i < things.Size(); i++)
		{
			Actor t = things[i];
			if (animAct[i] < 0 || t == null)
			{
				continue;
			}
			int age = level.maptime - animSince[i];
			// RotMG's timing: its two frames over the period the client sent (an attack over its
			// rate of fire, walking by speed), from when the action started.
			int ms = i < animMs.Size() && animMs[i] > 0 ? animMs[i] : (animAct[i] == 2 ? 300 : 400);
			bool second = FrameHalf(age, ms);
			int frame = 0;
			if (animAct[i] == 2)
			{
				frame = second ? 8 : 7;    // H, I
			}
			else if (animAct[i] == 1)
			{
				frame = second ? 6 : 5;    // F, G
			}
			t.frame = frame;
			Vector2 a = ViewDir(t.pos - eyePos, yaw, pitch);
			Vector2 b = ViewDir(t.pos + (cos(animYaw[i]), sin(animYaw[i]), 0) * 16 - eyePos, yaw, pitch);
			if (a.x < 1e8 && b.x < 1e8)
			{
				t.bSPRITEFLIP = b.x < a.x;
			}
		}
	}

	// Whether TICS into an animation whose two frames take MS (as RotMG's p = t % MS / MS,
	// frame int(p * 2)) shows its second frame.
	static bool FrameHalf(int tics, int ms)
	{
		double t = tics * 1000.0 / TICRATE;
		return (t % max(ms, 1)) * 2 >= ms;
	}

	// Where D (from your eye) lands on the screen, as x right and y up over depth; far off if
	// behind you.
	static Vector2 ViewDir(Vector3 d, double yaw, double pitch)
	{
		double fwd = d.x * cos(yaw) + d.y * sin(yaw);
		double right = d.x * sin(yaw) - d.y * cos(yaw);
		double depth = fwd * cos(pitch) - d.z * sin(pitch);
		double up = fwd * sin(pitch) + d.z * cos(pitch);
		if (depth < 1)
		{
			return (1e9, 1e9);
		}
		return (right / depth, up / depth);
	}

	// Your input as a direction on the ground (unit length, or zero). Confused, RotMG turns your
	// keys a quarter round and mirrors them (Player.setRelativeMovement: x = -y, y = -x):
	// forward walks right, right walks forward, back walks left, left walks back.
	Vector2 InputDir(PlayerInfo p)
	{
		double forward = p.cmd.forwardmove;
		double side = p.cmd.sidemove;
		if (cond0 & COND_CONFUSED)
		{
			double was = forward;
			forward = side;
			side = was;
		}
		if (forward == 0 && side == 0)
		{
			return (0, 0);
		}
		double a = p.mo.angle;
		Vector2 dir = (cos(a), sin(a)) * forward + (sin(a), -cos(a)) * side;
		return dir.Unit();
	}

	// Doom walks you this tic (see `control`).
	void Walk(PlayerInfo p)
	{
		Actor mo = p.mo;
		double tile = eye / (0.8 * 0.85);
		Vector2 at = mo.pos.xy;
		Vector2 dir = InputDir(p);
		bool moving = dir.x != 0 || dir.y != 0 || walkPush.x != 0 || walkPush.y != 0;
		int n = pathX.Size();
		double lead = walkSpeed * LEAD_SECONDS + tile * LEAD_TILES + walkPush.Length() * LEAD_SECONDS;
		// A conveyor carries you along, walking or not, through RotMG's walls as you walk.
		if (walkPush.x != 0 || walkPush.y != 0)
		{
			at = WalkTo(at, at + walkPush / 35.0, tile);
		}
		if (moving)
		{
			// Ease off while RotMG falls behind (a slow frame, a step it took a different way),
			// so it catches up instead of you being yanked back to it at LEAD's edge.
			double f = 1.0;
			if (n > 0)
			{
				double behind = (at - (pathX[n - 1], pathY[n - 1])).Length();
				f = behind <= lead * 0.5 ? 1.0 : clamp((lead - behind) / (lead * 0.5), 0.25, 1.0);
			}
			Vector2 want = dir * walkSpeed * f / 35.0;
			Vector2 was = at;
			at = WalkTo(at, at + want, tile);
			if ((at - was).Length() < want.Length() * 0.5)
			{
				at = IntoGap(at, want, tile);
			}
		}
		if (n > 0)
		{
			Vector2 rp = (pathX[n - 1], pathY[n - 1]);
			Vector2 err = at - rp;
			if (err.Length() > lead)
			{
				at = rp + err.Unit() * lead;   // RotMG couldn't follow (a wall, a push...): you can't either
				walkClamps++;
				walkClampMax = max(walkClampMax, err.Length() / tile);
			}
			else if (!moving && level.maptime - lastReportAt > 3 && err.Length() > tile * 0.02)
			{
				at -= err * 0.25;              // standing, RotMG settled: meet it
			}
		}
		if ((at - mo.pos.xy).Length() > 0.001)
		{
			mo.SetOrigin((at.x, at.y, mo.floorz), true);
		}
		mo.vel.xy = (0, 0);
		if (level.maptime - walkStatAt >= 35 * 2)
		{
			if (walkClamps > 0 || walkBlocks > 0)
			{
				Console.PrintfEx(PRINT_HIGH | PRINT_NONOTIFY, "[romtg] walk: pulled back to RotMG %d times (up to %.2f tiles ahead), stopped by a square %d times, grid %s",
					walkClamps, walkClampMax, walkBlocks, gridCells.Size() > 0 ? "known" : "missing");
			}
			walkStatAt = level.maptime;
			walkClamps = walkBlocks = 0;
			walkClampMax = 0;
		}
		if ((at - lastGoto).Length() > 0.01 || level.maptime - lastGotoAt >= RESEND_TICS)
		{
			lastGoto = at;
			lastGotoAt = level.maptime;
			RomtgBridge.Send(String.Format("goto %.2f %.2f", at.x, at.y));
		}
	}

	// RotMG's Player.walkTo (modifyMove, modifyStep), line for line, in grid coordinates (squares
	// from the grid's corner, so always positive as RotMG's are): walls are only checked where
	// you cross a half-square line, and you're stopped on that line. Checking every step instead
	// kept you out of one-square gaps in walls that RotMG lets you through (Ryan, 2026-11-15).
	const MOVE_THRESHOLD = 0.4;
	Vector2 walkFrom;               // where this walk started (RotMG's square_), grid coordinates

	Vector2 WalkTo(Vector2 from, Vector2 to, double tile)
	{
		if (gridCells.Size() == 0)
		{
			return to;
		}
		Vector2 g = ToGrid(from, tile), target = ToGrid(to, tile);
		walkFrom = g;
		double dx = target.x - g.x, dy = target.y - g.y;
		if (abs(dx) < MOVE_THRESHOLD && abs(dy) < MOVE_THRESHOLD)
		{
			g = ModifyStep(g, target);
		}
		else
		{
			double stepSize = MOVE_THRESHOLD / max(abs(dx), abs(dy));
			double d = 0;
			bool done = false;
			while (!done)
			{
				if (d + stepSize >= 1)
				{
					stepSize = 1 - d;
					done = true;
				}
				g = ModifyStep(g, (g.x + dx * stepSize, g.y + dy * stepSize));
				d += stepSize;
			}
		}
		return FromGrid(g, tile);
	}

	// Stopped walking (almost) straight at a wall with a walkable square through it: slide
	// sideways onto that square's middle line, where RotMG's rule lets you through. In RotMG
	// you come at a gap at an angle and its walkTo slides you onto the line; Doom's mouse aims
	// straight, so one-square gaps in walls stopped you (Ryan, 2026-11-15).
	Vector2 IntoGap(Vector2 at, Vector2 want, double tile)
	{
		if (gridCells.Size() == 0)
		{
			return at;
		}
		Vector2 g = ToGrid(at, tile);
		Vector2 w = (want.x / tile, -want.y / tile);   // in grid squares (y south)
		double step = w.Length();
		if (step <= 0)
		{
			return at;
		}
		bool alongY = abs(w.y) >= abs(w.x);
		int cx = Trunc(g.x) - gridR, cy = Trunc(g.y) - gridR;
		int ax = alongY ? cx : cx + (w.x > 0 ? 1 : -1);
		int ay = alongY ? cy + (w.y > 0 ? 1 : -1) : cy;
		if (GridCell(ax, ay) != 0)
		{
			return at;   // nothing to get through ahead
		}
		double side = alongY ? g.x : g.y;
		double middle = Trunc(side) + 0.5;
		double move = clamp(middle - side, -step, step);
		if (abs(move) < 0.001)
		{
			return at;
		}
		Vector2 to = alongY ? (g.x + move, g.y) : (g.x, g.y + move);
		return WalkTo(at, FromGrid(to, tile), tile);
	}

	Vector2 ToGrid(Vector2 p, double tile)
	{
		return (OnHalf((p.x - gridAt.x) / tile + gridR), OnHalf(-(p.y - gridAt.y) / tile + gridR));
	}

	// A square's middle line exactly: RotMG's rule only lets you through a one-square gap on
	// it, and Doom's units round it off by a hair.
	static double OnHalf(double v)
	{
		double h = floor(v) + 0.5;
		return abs(v - h) < 0.002 ? h : v;
	}

	Vector2 FromGrid(Vector2 g, double tile)
	{
		return (gridAt.x + (g.x - gridR) * tile, gridAt.y - (g.y - gridR) * tile);
	}

	static int Trunc(double v)
	{
		return int(v);   // as RotMG's int(): toward zero (grid coordinates are positive)
	}

	static bool HalfCross(double from, double to)
	{
		return (from % 0.5 == 0 && to != from) || Trunc(from / 0.5) != Trunc(to / 0.5);
	}

	Vector2 ModifyStep(Vector2 cur, Vector2 to)
	{
		bool xCross = HalfCross(cur.x, to.x);
		bool yCross = HalfCross(cur.y, to.y);
		if ((!xCross && !yCross) || GridValid(to))
		{
			return to;
		}
		double nextX = 0, nextY = 0;
		if (xCross)
		{
			nextX = to.x > cur.x ? Trunc(to.x * 2) / 2.0 : Trunc(cur.x * 2) / 2.0;
			if (Trunc(nextX) > Trunc(cur.x))
			{
				nextX -= 0.01;
			}
		}
		if (yCross)
		{
			nextY = to.y > cur.y ? Trunc(to.y * 2) / 2.0 : Trunc(cur.y * 2) / 2.0;
			if (Trunc(nextY) > Trunc(cur.y))
			{
				nextY -= 0.01;
			}
		}
		if (!xCross)
		{
			return (to.x, nextY);
		}
		if (!yCross)
		{
			return (nextX, to.y);
		}
		double xDist = to.x > cur.x ? to.x - nextX : nextX - to.x;
		double yDist = to.y > cur.y ? to.y - nextY : nextY - to.y;
		if (xDist > yDist)
		{
			if (GridValid((to.x, nextY))) return (to.x, nextY);
			if (GridValid((nextX, to.y))) return (nextX, to.y);
		}
		else
		{
			if (GridValid((nextX, to.y))) return (nextX, to.y);
			if (GridValid((to.x, nextY))) return (to.x, nextY);
		}
		walkBlocks++;
		return (nextX, nextY);
	}

	// RotMG's Player.isValidPosition at grid point G (walkFrom's square always allowed).
	bool GridValid(Vector2 g)
	{
		int cx = Trunc(g.x) - gridR, cy = Trunc(g.y) - gridR;
		int fx = Trunc(walkFrom.x) - gridR, fy = Trunc(walkFrom.y) - gridR;
		if ((cx != fx || cy != fy) && GridCell(cx, cy) != 0)
		{
			return false;
		}
		double xf = g.x - Trunc(g.x), yf = g.y - Trunc(g.y);
		if (xf < 0.5)
		{
			if (GridCell(cx - 1, cy) == 2) return false;
			if (yf < 0.5 && (GridCell(cx, cy - 1) == 2 || GridCell(cx - 1, cy - 1) == 2)) return false;
			if (yf > 0.5 && (GridCell(cx, cy + 1) == 2 || GridCell(cx - 1, cy + 1) == 2)) return false;
		}
		else if (xf > 0.5)
		{
			if (GridCell(cx + 1, cy) == 2) return false;
			if (yf < 0.5 && (GridCell(cx, cy - 1) == 2 || GridCell(cx + 1, cy - 1) == 2)) return false;
			if (yf > 0.5 && (GridCell(cx, cy + 1) == 2 || GridCell(cx + 1, cy + 1) == 2)) return false;
		}
		else if (yf < 0.5)
		{
			if (GridCell(cx, cy - 1) == 2) return false;
		}
		else if (yf > 0.5)
		{
			if (GridCell(cx, cy + 1) == 2) return false;
		}
		return true;
	}

	// (Before RotMG's rule: from FROM towards TO in small steps, sliding along what blocks.)
	Vector2 Step(Vector2 from, Vector2 to, double tile)
	{
		Vector2 d = to - from;
		int steps = max(1, int(ceil(d.Length() / (tile * 0.1))));
		d /= steps;
		Vector2 cur = from;
		for (int i = 0; i < steps; i++)
		{
			Vector2 next = cur + d;
			if (Valid(next, from, tile))
			{
				cur = next;
			}
			else if (Valid((next.x, cur.y), from, tile))
			{
				cur = (next.x, cur.y);
			}
			else if (Valid((cur.x, next.y), from, tile))
			{
				cur = (cur.x, next.y);
			}
			else
			{
				walkBlocks++;
				break;
			}
		}
		return cur;
	}

	// A grid square: 0 walkable, 1 not, 2 not and its edge blocks the next square too;
	// unknown squares walkable (RotMG's report pulls you back if they weren't).
	int GridCell(int cx, int cy)
	{
		int w = 2 * gridR + 1;
		int i = cx + gridR, j = cy + gridR;
		if (gridCells.Size() != w * w || i < 0 || j < 0 || i >= w || j >= w)
		{
			return 0;
		}
		return gridCells[j * w + i];
	}

	// RotMG's Player.isValidPosition, in grid squares from the grid's middle one (x east, y
	// south as RotMG has them): a square you aren't in must be walkable, and within half a
	// square of a blocking square's edge you can't stand.
	bool Valid(Vector2 pt, Vector2 from, double tile)
	{
		if (gridCells.Size() == 0)
		{
			return true;
		}
		double x = (pt.x - gridAt.x) / tile, y = -(pt.y - gridAt.y) / tile;
		int cx = int(floor(x)), cy = int(floor(y));
		int fx = int(floor((from.x - gridAt.x) / tile)), fy = int(floor(-(from.y - gridAt.y) / tile));
		if ((cx != fx || cy != fy) && GridCell(cx, cy) != 0)
		{
			return false;
		}
		double xf = x - cx, yf = y - cy;
		if (xf < 0.5)
		{
			if (GridCell(cx - 1, cy) == 2) return false;
			if (yf < 0.5 && (GridCell(cx, cy - 1) == 2 || GridCell(cx - 1, cy - 1) == 2)) return false;
			if (yf > 0.5 && (GridCell(cx, cy + 1) == 2 || GridCell(cx - 1, cy + 1) == 2)) return false;
		}
		else if (xf > 0.5)
		{
			if (GridCell(cx + 1, cy) == 2) return false;
			if (yf < 0.5 && (GridCell(cx, cy - 1) == 2 || GridCell(cx + 1, cy - 1) == 2)) return false;
			if (yf > 0.5 && (GridCell(cx, cy + 1) == 2 || GridCell(cx + 1, cy + 1) == 2)) return false;
		}
		else if (yf < 0.5)
		{
			if (GridCell(cx, cy - 1) == 2) return false;
		}
		else if (yf > 0.5)
		{
			if (GridCell(cx, cy + 1) == 2) return false;
		}
		return true;
	}

	// How evenly you moved, tic by tic (logged while you move): the step each tic in tiles,
	// still tics among moving ones, and position reports per tic.
	void MotionStats(Actor mo)
	{
		double tile = eye > 0 ? eye / (0.8 * 0.85) : 64;
		double step = (mo.pos.xy - statLast).Length() / tile;
		statLast = mo.pos.xy;
		if (step > 2)
		{
			return;   // a teleport or a shift
		}
		if (statTics == 0)
		{
			statSum = 0; statMax = 0; statMin = 99; statStill = 0; statPLines = 0;
			statStart = level.maptime;
		}
		statTics++;
		statSum += step;
		statMax = max(statMax, step);
		if (step > 0.0001)
		{
			statMin = min(statMin, step);
		}
		else
		{
			statStill++;
		}
		if (statTics >= STATS_TICS)
		{
			if (statSum > 1)   // you moved
			{
				double mean = statSum / (statTics - statStill);
				Console.PrintfEx(PRINT_HIGH | PRINT_NONOTIFY, "[romtg] motion: step per tic min %.3f mean %.3f max %.3f tiles, %d still of %d tics, %.2f reports a tic",
					statMin, mean, statMax, statStill, statTics, double(statPLines) / statTics);
			}
			statTics = 0;
		}
	}

	// Frame times (the stutter could be slow frames as well as uneven steps): logged every 3 s
	// when a frame took over 20 ms, with the slowest ground redraw.
	ui void FrameStats()
	{
		double now = MSTimeF();
		if (frameLast > 0)
		{
			double f = now - frameLast;
			frames++;
			frameMax = max(frameMax, f);
			if (f > 20)
			{
				framesSlow++;
			}
		}
		frameLast = now;
		if (now - frameSince >= 3000)
		{
			if (framesSlow > 0 || frameMax > 12)
			{
				Console.PrintfEx(PRINT_HIGH | PRINT_NONOTIFY, "[romtg] frames: %d in 3 s, slowest %.1f ms, %d over 20 ms; ground redrawn %d times, slowest %.1f ms",
					frames, frameMax, framesSlow, groundDraws, groundMax);
			}
			frameSince = now;
			frames = framesSlow = groundDraws = 0;
			frameMax = groundMax = 0;
		}
	}

	// Things towards the edge of sight see-through, the further the fainter (SHOW_FADE_*).
	void FadeThings(Actor mo)
	{
		for (int i = 0; i < things.Size(); i++)
		{
			if (things[i] != null)
			{
				FadeThing(things[i], mo, i);
			}
		}
	}

	// One thing (and its wall sides, and health bar if ID has one) faded for its distance.
	void FadeThing(Actor t, Actor mo, int id)
	{
		double tile = eye > 0 ? eye / (0.8 * 0.85) : 64;
		double d = (t.pos.xy - mo.pos.xy).Length() / tile;
		double a = d <= SHOW_FADE_FROM ? 1.0 : clamp((SHOW_FADE_TO - d) / (SHOW_FADE_TO - SHOW_FADE_FROM), 0.0, 1.0);
		SetShowAlpha(t, a);
		RomtgWall w = RomtgWall(t);
		if (w != null)
		{
			for (int j = 0; j < w.parts.Size(); j++)
			{
				if (w.parts[j] != null)
				{
					SetShowAlpha(w.parts[j], a);
				}
			}
		}
		if (id >= 0 && id < bars.Size() && bars[id] != null)
		{
			SetShowAlpha(bars[id], a);
		}
	}

	// Pieces are drawn normally; while fading, translucent. Pieces drawn some other way
	// (stencils...) keep their style and just take the alpha.
	static void SetShowAlpha(Actor t, double a)
	{
		int style = t.GetRenderStyle();
		if (style == STYLE_Normal || style == STYLE_Translucent)
		{
			if (a >= 0.999)
			{
				if (style != STYLE_Normal) t.A_SetRenderStyle(1.0, STYLE_Normal);
			}
			else if (style != STYLE_Translucent || abs(t.alpha - a) > 0.02)
			{
				t.A_SetRenderStyle(a, STYLE_Translucent);
			}
		}
		else if (abs(t.alpha - a) > 0.02)
		{
			t.alpha = a;
		}
	}

	// Solid while fully drawn (so a far wall's colour square stays over its ground square, by
	// depth), see-through only in the fading ring.
	static void SetFarAlpha(Actor t, double a)
	{
		if (a >= 0.999)
		{
			if (t.GetRenderStyle() != STYLE_Stencil) t.A_SetRenderStyle(1.0, STYLE_Stencil);
		}
		else if (t.GetRenderStyle() != STYLE_TranslucentStencil || abs(t.alpha - a) > 0.02)
		{
			t.A_SetRenderStyle(a, STYLE_TranslucentStencil);
		}
	}

	double FarAlpha(Actor t, Actor mo)
	{
		double tile = eye > 0 ? eye / (0.8 * 0.85) : 64;   // eye = tile * 0.8 * 0.85 (bridge.py)
		double d = (t.pos.xy - mo.pos.xy).Length() / tile;
		return d <= FADE_FROM ? 1.0 : clamp((FADE_TO - d) / (FADE_TO - FADE_FROM), 0.0, 1.0);
	}

	void DeleteFloat(int i)
	{
		floatThing.Delete(i); floatX.Delete(i); floatY.Delete(i); floatZ.Delete(i);
		floatColor.Delete(i); floatAt.Delete(i); floatText.Delete(i);
	}

	// The top of an upright picture: it hangs from its middle, LIFT_TILES above the floor.
	// One dot of an effect: COLOUR, SIZE units, for TICS, moving VEL a tic, falling by GRAVITY.
	void FxDot(Vector3 at, int rgb, double size, int tics, Vector3 vel, double gravity = 0)
	{
		let d = RomtgDrop(Actor.Spawn("RomtgDrop", at));
		if (d != null)
		{
			d.Start(rgb, size, max(1, tics), vel, gravity);
			drops.Push(d);
		}
	}

	void HealSparkle(Vector2 at, double tile)
	{
		double a = frandom(0, 360), r = frandom(0, tile * 0.4);
		FxDot((at.x + cos(a) * r, at.y + sin(a) * r, tile * 0.1), 0x40FF40, max(2.0, tile * 0.07), 25,
			(0, 0, tile * 0.6 / 35.0));
	}

	// RotMG's ShowEffect kinds, drawn with dots (RomtgDrop) as RotMG draws them with particles:
	// TARGET is the character it's on (you: MINE), P1 and P2 its two points, R1 and R2 the
	// numbers RotMG uses as radii (P1's and P2's x, scaled), SECS how long (throws).
	void ShowEffect(Actor mo, int type, Vector2 target, Vector2 p1, Vector2 p2, double r1, double r2, int rgb, double secs, bool mine)
	{
		double tile = eye > 0 ? eye / (0.8 * 0.85) : 64;
		double low = tile * 0.15, mid = tile * 0.4;
		double dsz = max(2.0, tile * 0.09);
		if (mine && mo != null)
		{
			target = mo.pos.xy;
		}
		switch (type)
		{
		case 1:     // heal: sparkles rising round the healed character
			for (int i = 0; i < 16; i++)
			{
				double a = i * 22.5, r = tile * 0.45;
				FxDot((target.x + cos(a) * r, target.y + sin(a) * r, low), rgb, dsz, 24, (0, 0, tile * 0.9 / 35.0));
			}
			break;
		case 2:     // teleport: a column of white sparkles
			for (int i = 0; i < 24; i++)
			{
				FxDot((p1.x + frandom(-1, 1) * tile * 0.3, p1.y + frandom(-1, 1) * tile * 0.3, frandom(0, tile)), 0xFFFFFF, dsz, 20,
					(0, 0, tile * 0.5 / 35.0));
			}
			break;
		case 3:     // stream: dots running from P1 to P2
		case 9:     // flow: from P1 to the character
		{
			Vector2 from = p1, to = type == 3 ? p2 : target;
			for (int i = 0; i < 16; i++)
			{
				int t = 10 + i;
				Vector2 v = (to - from) / t;
				FxDot((from.x, from.y, mid), rgb, dsz, t, (v.x, v.y, 0));
			}
			break;
		}
		case 4:     // throw: an arc from the character to P1 over SECS
		case 16:    // a thrown projectile, the same arc
		{
			int t = max(4, int(secs * 35));
			Vector2 v = (p1 - target) / t;
			double g = tile * 2.0 / (t * t) * 4;   // peaks about two tiles up
			FxDot((target.x, target.y, mid), type == 16 ? 0xFFFFFF : rgb, max(3.0, tile * 0.22), t, (v.x, v.y, g * t / 2), g);
			break;
		}
		case 5:     // nova: a ring from the character out to R1
		case 8:     // burst: a ring from P1 out to R2
		{
			Vector2 c = type == 5 ? target : p1;
			double radius = type == 5 ? r1 : r2;
			for (int i = 0; i < 40; i++)
			{
				double a = i * 9;
				FxDot((c.x, c.y, low), rgb, dsz, 14, (cos(a) * radius / 14, sin(a) * radius / 14, 0));
			}
			break;
		}
		case 10:    // ring: a ring at R1 round the character
			for (int i = 0; i < 36; i++)
			{
				double a = i * 10;
				FxDot((target.x + cos(a) * r1, target.y + sin(a) * r1, low), rgb, dsz, 18, (0, 0, 0));
			}
			break;
		case 12:    // collapse: a ring at R2 round P1 closing in
			for (int i = 0; i < 40; i++)
			{
				double a = i * 9;
				FxDot((p1.x + cos(a) * r2, p1.y + sin(a) * r2, low), rgb, dsz, 14, (-cos(a) * r2 / 14, -sin(a) * r2 / 14, 0));
			}
			break;
		case 6:     // poison: a cloud round the character
			for (int i = 0; i < 18; i++)
			{
				FxDot((target.x + frandom(-1, 1) * tile * 0.6, target.y + frandom(-1, 1) * tile * 0.6, frandom(low, mid * 2)), rgb, dsz * 1.5, 35,
					(frandom(-1, 1) * tile * 0.2 / 35.0, frandom(-1, 1) * tile * 0.2 / 35.0, tile * 0.2 / 35.0));
			}
			break;
		case 7:     // line: the character to P1
		case 11:    // lightning: the same, jagged
		{
			int n = 14;
			for (int i = 0; i <= n; i++)
			{
				Vector2 at = target + (p1 - target) * i / n;
				double jag = type == 11 && i > 0 && i < n ? tile * 0.3 : 0;
				FxDot((at.x + frandom(-jag, jag), at.y + frandom(-jag, jag), mid + frandom(-jag, jag)), rgb, dsz, type == 11 ? 8 : 14, (0, 0, 0));
			}
			break;
		}
		case 13:    // cone blast: dots fanning out from the character towards P1
		{
			double dir = atan2(p1.y - target.y, p1.x - target.x);
			for (int i = 0; i < 24; i++)
			{
				double a = dir + frandom(-35, 35);
				double sp = (r2 > 0 ? r2 : tile * 3) / 14;
				FxDot((target.x, target.y, mid), rgb, dsz, 14, (cos(a) * sp, sin(a) * sp, 0));
			}
			break;
		}
		case 14:    // jitter: the view shakes
			if (mo != null)
			{
				mo.A_Quake(2, 8, 0, 64, "");
			}
			break;
		case 15:    // flash: a glow of the colour round the character
			for (int i = 0; i < 20; i++)
			{
				double a = frandom(0, 360);
				FxDot((target.x + cos(a) * tile * 0.35, target.y + sin(a) * tile * 0.35, frandom(low, mid * 1.6)), rgb, dsz * 1.3, 10, (0, 0, 0));
			}
			break;
		}
	}

	// Where texts over a thing start rising from: its head, or above its name tag if it has one
	// (healing and potion texts over players covered their names, Ryan 2026-11-15).
	clearscope double TextBase(Actor t)
	{
		double tile = eye > 0 ? eye / (0.8 * 0.85) : 64;
		int id = things.Find(t);
		bool named = id < things.Size() && id < nameText.Size() && nameText[id].Length() > 0;
		return HeadOf(t) + (named ? tile * 0.35 : 0);
	}

	clearscope double HeadOf(Actor t)
	{
		double tile = eye > 0 ? eye / (0.8 * 0.85) : 64;
		return max(2 * t.pos.z - max(1.0, tile * LIFT_TILES), tile * 0.5);
	}

	// RotMG's fountain particles (FountainEffect.as): one every 50 ms from the fountain's top,
	// thrown up and out at 0.8 tiles/s in a random direction, falling until they reach the
	// ground, about 1.4 s. RotMG's own numbers (up at 6.5, down at 4.9) are in its height units,
	// which its top-down view shows squashed; in tiles they threw the spray five tiles high, so
	// the arc here is a third of the height, played FOUNTAIN_SPEED times faster. One a tic.
	void Fountains()
	{
		if (eye <= 0)
		{
			return;
		}
		double tile = eye / (0.8 * 0.85);
		double perTic = tile / 35.0;
		for (int i = drops.Size() - 1; i >= 0; i--)
		{
			if (drops[i].life <= 0)
			{
				drops[i].Destroy();
				drops.Delete(i);
			}
		}
		// Healing: green sparkles rising round the character (RotMG's HealingEffect), a few a tic.
		for (int i = 0; i < healing.Size() && i < things.Size(); i++)
		{
			if (healing[i] && things[i] != null && level.maptime % 3 == 0)
			{
				HealSparkle(things[i].pos.xy, tile);
			}
		}
		PlayerInfo hp = players[consoleplayer];
		if (meHealing && hp != null && hp.mo != null && level.maptime % 3 == 0)
		{
			HealSparkle(hp.mo.pos.xy, tile);
		}
		// Shots' particle trails: RotMG's sparks (Projectile.draw, SparkParticle): three a frame
		// where the shot is, drifting up to 3 tiles a second, shrinking to nothing over their
		// lifetime. Two a tic here (Doom ticks slower than RotMG draws).
		for (int i = 0; i < trailTics.Size(); i++)
		{
			if (trailTics[i] <= 0 || i >= things.Size() || things[i] == null)
			{
				continue;
			}
			for (int k = 0; k < 2; k++)
			{
				if (trailShare[i] < 1 && frandom(0, 1) > trailShare[i])
				{
					continue;
				}
				let spark = RomtgDrop(Actor.Spawn("RomtgDrop", things[i].pos));
				if (spark != null)
				{
					spark.Start(trailColor[i], max(2.0, tile * 0.14), trailTics[i],
						(frandom(-3, 3) * perTic, frandom(-3, 3) * perTic, 0), 0);
					spark.shrink = true;
					drops.Push(spark);
				}
			}
		}
		for (int i = fxThing.Size() - 1; i >= 0; i--)
		{
			Actor t = fxThing[i];
			if (t == null)
			{
				fxThing.Delete(i);
				fxColor.Delete(i);
				continue;
			}
			double a = frandom(0, 360);
			double top = tile * 0.75 - (t.pos.z - 0.5) ;   // the fountain's top, from its base (z 0.5)
			// A drop: an actor of ours, not a Doom particle. Particles can't be moved or
			// removed, so after a re-centre or a portal the spray hung on where the fountain had
			// been, a random fountain in the middle of nowhere (Ryan, 2026-11-13).
			let drop = RomtgDrop(Actor.Spawn("RomtgDrop", t.pos + (0, 0, top)));
			if (drop != null)
			{
				drop.Start(fxColor[i], max(4.0, tile * 0.16), 58,   // up and all the way back down (~1.65 s)
					// out only a little, so the spray falls back into the basin (Ryan, 2026-11-12)
					(cos(a) * 0.25 * FOUNTAIN_SPEED * perTic, sin(a) * 0.25 * FOUNTAIN_SPEED * perTic,
					 6.5 * FOUNTAIN_HEIGHT * FOUNTAIN_SPEED * perTic),
					4.9 * FOUNTAIN_HEIGHT * FOUNTAIN_SPEED * FOUNTAIN_SPEED * tile / (35.0 * 35.0));
				drops.Push(drop);
			}
		}
	}

	void SetFloorPan()
	{
		for (int i = 0; i < level.sectors.Size(); i++)
		{
			level.sectors[i].SetXOffset(Sector.floor, -panX);
			level.sectors[i].SetYOffset(Sector.floor, panY);
		}
	}

	void SetGround(int id, int kind, double x, double y, string sprite, int rgb)
	{
		if (id < 0)
		{
			return;
		}
		if (id >= gKind.Size())
		{
			gKind.Resize(id + 1);
			gColor.Resize(id + 1);
			gX.Resize(id + 1);
			gY.Resize(id + 1);
			gSprite.Resize(id + 1);
		}
		if (id >= gAnim.Size())
		{
			gAnim.Resize(id + 1);
			gDx.Resize(id + 1);
			gDy.Resize(id + 1);
		}
		gAnim[id] = 0;
		gKind[id] = kind;
		gX[id] = x;
		gY[id] = y;
		gSprite[id] = sprite;
		gColor[id] = rgb;
		groundVersion++;
	}

	clearscope static int Cell(double v)
	{
		int n = GROUND_PX / CELL_PX;
		int c = int(floor(v)) % n;
		return c < 0 ? c + n : c;
	}

	// The whole ground into RTGROUND: the background colour, the tiles in sight as their
	// pictures, the far ones as their minimap colours fading into the background over the last
	// tiles of sight, and the far walls and trees over them. A tile's cell: its place in tiles,
	// wrapping round the texture as the floor repeats it (x east, y south, as flats run).
	ui void DrawGround()
	{
		Canvas cv = TexMan.GetCanvas("RTGROUND");
		if (cv == null || eye <= 0)
		{
			return;
		}
		double tile = eye / (0.8 * 0.85);
		Color bg = Color(255, (bgColor >> 16) & 255, (bgColor >> 8) & 255, bgColor & 255);
		cv.Clear(0, 0, GROUND_PX, GROUND_PX, bg);
		PlayerInfo p = players[consoleplayer];
		Vector2 me = (p != null && p.mo != null) ? p.mo.pos.xy : (0, 0);
		// Past the far ground: nothing but the background (Ryan: only the sky out there; the
		// faint ground pattern that was here read as stray ground past the end of sight).
		for (int pass = 1; pass <= 3; pass++)
		{
			for (int i = 0; i < gKind.Size(); i++)
			{
				if (gKind[i] != pass)
				{
					continue;
				}
				int cx = Cell((gX[i] - panX) / tile) * CELL_PX;
				int cy = Cell(-(gY[i] - panY) / tile) * CELL_PX;
				if (pass == 1)
				{
					TextureID tex = TexMan.CheckForTexture(gSprite[i] .. "A0", TexMan.Type_Sprite);
					if (!tex.IsValid())
					{
						continue;
					}
					// The fog: the ground fades into the background colour over the same tiles
					// as everything standing on it (SHOW_FADE_*), gone by the end of sight
					// (Ryan, 2026-11-13: the ground showed past where things faded out).
					double sd = ((gX[i], gY[i]) - me).Length() / tile;
					double fog = sd <= SHOW_FADE_FROM ? 1.0 : clamp((SHOW_FADE_TO - sd) / (SHOW_FADE_TO - SHOW_FADE_FROM), 0.0, 1.0);
					if (fog <= 0.01)
					{
						continue;
					}
					if (i >= gAnim.Size() || gAnim[i] == 0)
					{
						cv.DrawTexture(tex, false, cx, cy, DTA_DestWidth, CELL_PX, DTA_DestHeight, CELL_PX, DTA_TopLeft, true, DTA_Alpha, fog);
						continue;
					}
					// Moving ground, as RotMG moves it (SquareFace.draw): the texture offset by
					// DX, DY texture widths a second (Flow) or by sin(DX t), sin(DY t) (Wave),
					// wrapping inside the cell: four copies, clipped to it.
					double secs = level.maptime / 35.0;
					double ou = gAnim[i] == 1 ? gDx[i] * secs : sin(gDx[i] * secs * 180.0 / M_PI);
					double ov = gAnim[i] == 1 ? gDy[i] * secs : sin(gDy[i] * secs * 180.0 / M_PI);
					double ox = (ou - floor(ou)) * CELL_PX, oy = (ov - floor(ov)) * CELL_PX;
					for (int k = 0; k < 4; k++)
					{
						cv.DrawTexture(tex, false, cx - ox + (k % 2) * CELL_PX, cy - oy + (k / 2) * CELL_PX,
							DTA_DestWidth, CELL_PX, DTA_DestHeight, CELL_PX, DTA_TopLeft, true,
							DTA_ClipLeft, cx, DTA_ClipTop, cy, DTA_ClipRight, cx + CELL_PX, DTA_ClipBottom, cy + CELL_PX, DTA_Alpha, fog);
					}
					continue;
				}
				double d = ((gX[i], gY[i]) - me).Length() / tile;
				double f = d <= FADE_FROM ? 1.0 : clamp((FADE_TO - d) / (FADE_TO - FADE_FROM), 0.0, 1.0);
				int rgb = gColor[i];
				int r = int(((rgb >> 16) & 255) * f + ((bgColor >> 16) & 255) * (1 - f));
				int g = int(((rgb >> 8) & 255) * f + ((bgColor >> 8) & 255) * (1 - f));
				int b = int((rgb & 255) * f + (bgColor & 255) * (1 - f));
				cv.Clear(cx, cy, cx + CELL_PX, cy + CELL_PX, Color(255, r, g, b));
			}
		}
	}

	// In water you sink to about the waist in RotMG: your eyes ease down a quarter of a tile.
	void Sink(PlayerInfo p)
	{
		let pp = PlayerPawn(p.mo);
		if (pp == null || eye <= 4)
		{
			return;
		}
		sunk = clamp(sunk + (sinking ? 0.08 : -0.08), 0.0, 1.0);
		double tile = eye / (0.8 * 0.85);
		double h = eye - sunk * tile * 0.25;
		pp.ViewHeight = h;
		p.viewheight = h;
	}

	// Health bars stay at their enemy's feet, a little towards you so they're never behind it.
	// Health bars at their things' feet, a little toward the camera so the bar shows in front
	// of the feet. Yours in third person further: below your character, as RotMG draws it under
	// you (it covered your feet, Ryan 2026-11-21).
	void PlaceBars(Actor mo, Vector3 view)
	{
		double tile = eye > 0 ? eye / (0.8 * 0.85) : 64;
		for (int i = barIds.Size() - 1; i >= 0; i--)
		{
			int id = barIds[i];
			Actor bar = id < bars.Size() ? bars[id] : null;
			Actor t = id < things.Size() ? things[id] : null;
			if (bar == null || t == null || id >= thingMax.Size() || thingMax[id] <= 0)
			{
				if (bar != null) bar.Destroy();
				if (id < bars.Size()) bars[id] = null;
				barIds.Delete(i);
				continue;
			}
			// Yours in third person is drawn by DrawSelfBar every frame instead (placed here once a
			// tic it lagged behind as you turned, Ryan 2026-11-21).
			bar.bINVISIBLE = thirdPerson && id == selfId;
			Vector2 to = view.xy - t.pos.xy;
			double len = to.Length();
			double ahead = tile * 0.3;
			Vector2 toward = len > 0.001 ? to / len * min(ahead, len * 0.5) : (0, 0);
			Vector3 at = (t.pos.x + toward.x, t.pos.y + toward.y, max(1.0, tile * LIFT_TILES));
			bar.SetOrigin(at, (at.xy - bar.pos.xy).Length() < 2 * tile);
		}
	}

	// Enemy ID's bar shows HP of MAX: frame A (empty) to U (full) of ZHPB (scripts/assets.py).
	void SetBar(int id)
	{
		if (id >= thingMax.Size() || thingMax[id] <= 0 || id >= things.Size() || things[id] == null)
		{
			return;
		}
		if (id >= bars.Size())
		{
			bars.Resize(id + 1);
		}
		if (bars[id] == null)
		{
			double tile = eye > 0 ? eye / (0.8 * 0.85) : 64;
			Actor bar = Actor.Spawn("RomtgBillboard", (things[id].pos.x, things[id].pos.y, max(1.0, tile * LIFT_TILES)));
			RomtgPiece.Dress(bar, "ZHPB", tile * 0.8 / 40.0);
			if (bar == null)
			{
				return;
			}
			bars[id] = bar;
			barIds.Push(id);
			if (id < things.Size() && things[id] != null)
			{
				SetShowAlpha(bar, things[id].GetRenderStyle() == STYLE_Translucent ? things[id].alpha : 1.0);   // faded as its enemy
			}
		}
		double frac = clamp(double(thingHp[id]) / thingMax[id], 0, 1);
		bars[id].frame = int(frac * 20 + 0.5);
	}

	override void WorldTick()
	{
		PlayerInfo p = players[consoleplayer];
		if (p == null || p.mo == null)
		{
			return;
		}
		for (int i = 0; i < MAX_LINES_PER_TIC; i++)
		{
			string line = RomtgBridge.Poll();
			if (line.Length() == 0)
			{
				break;
			}
			Handle(line, p.mo);
		}
		if (control && walkSpeed > 0 && eye > 0)
		{
			Walk(p);
		}
		else
		{
			Replay(p.mo);
		}
		AimShots(p);
		Animate(p);
		MotionStats(p.mo);
		SendMove(p);
		SendFire(p);
		SendThrow(p);
		Camera(p);
		KeepSelf(p);
		PlaceBars(p.mo, ViewFrom(p));
		Fountains();
		Sink(p);
		// Moving ground in sight: the floor is redrawn every tic to move it smoothly.
		{
			for (int i = 0; i < gAnim.Size(); i++)
			{
				if (gAnim[i] != 0 && i < gKind.Size() && gKind[i] == 1)
				{
					groundVersion++;
					break;
				}
			}
		}
		if (level.maptime % FADE_EVERY == 0)
		{
			FadeFar(p.mo);
		}
		if (level.maptime % SHOW_FADE_EVERY == 0)
		{
			FadeThings(p.mo);
		}
		for (int i = floatAt.Size() - 1; i >= 0; i--)
		{
			if (level.maptime - floatAt[i] > FLOAT_TICS)
			{
				DeleteFloat(i);
			}
			else if (floatThing[i] != null)
			{
				floatX[i] = floatThing[i].pos.x;
				floatY[i] = floatThing[i].pos.y;
				floatZ[i] = TextBase(floatThing[i]);
			}
		}
	}

	// How far a throw goes for a look PITCH (degrees, down positive): a tile at your feet
	// looking well down, the ability's farthest looking up, evenly between (Ryan, 2026-11-18:
	// "the higher you look the further it throws").
	clearscope double ThrowDistance(double pitch)
	{
		double tile = eye > 0 ? eye / (0.8 * 0.85) : 64;
		// In third person you always look down: near = looking nearly straight down at yourself.
		double nearP = thirdPerson ? CAM_PITCH_MAX : THROW_PITCH_NEAR;
		double farP = thirdPerson ? CAM_PITCH_MIN : THROW_PITCH_FAR;
		double t = clamp((nearP - pitch) / (nearP - farP), 0, 1);
		return tile + (max(throwMax, tile) - tile) * t;
	}

	// First or third person: Doom's view moved back along your look (SetViewPos, relative to
	// your angles), your look kept pointing down at yourself.
	void Camera(PlayerInfo p)
	{
		if (thirdPerson)
		{
			double tile = eye > 0 ? eye / (0.8 * 0.85) : 64;
			// The camera's tilt never moves: Doom's look limits pinned to it, so neither the tic
			// (CheckPitch) nor the frames between (the mouse shown at once, clamped to the same
			// limits) can tilt it; it was nudged and snapped back (Ryan, 2026-11-21). The mouse's
			// up and down (this tic's cmd.pitch, up positive) only aims throws.
			if (!camSet)
			{
				pitchMin = p.MinPitch;
				pitchMax = p.MaxPitch;
			}
			p.MinPitch = CAM_PITCH;
			p.MaxPitch = CAM_PITCH;
			throwPitch = clamp(throwPitch - p.cmd.pitch * (360. / 65536.), CAM_PITCH_MIN, CAM_PITCH_MAX);
			p.mo.pitch = CAM_PITCH;
			p.mo.SetViewPos((-tile * CAM_DIST_TILES, 0, 0), 0);
			camSet = true;
		}
		else if (camSet)
		{
			p.mo.SetViewPos((0, 0, 0), 0);
			p.MinPitch = pitchMin;
			p.MaxPitch = pitchMax;
			camSet = false;
		}
	}

	// Your own character's picture stands where Doom's player is, every tic (the bridge's idea of
	// where you are is RotMG's, a little behind Doom's).
	void KeepSelf(PlayerInfo p)
	{
		if (!thirdPerson || selfId < 0 || selfId >= things.Size() || things[selfId] == null)
		{
			return;
		}
		Actor t = things[selfId];
		Vector3 to = (p.mo.pos.x, p.mo.pos.y, t.pos.z);
		t.SetOrigin(to, (to.xy - t.pos.xy).Length() < 64);
		// Animated as RotMG animates you (the client sends no `an` for you): walking while you
		// move, attacking while you fire, seen from behind (the camera is behind you): RotMG's
		// back frames J-N if it has them (assets.py back_frames), else its side ones.
		bool moving = (p.mo.pos.xy - selfWas).Length() > 0.5;
		selfWas = p.mo.pos.xy;
		bool firing = control && (p.cmd.buttons & BT_ATTACK);
		int k = 0;
		if (firing)
		{
			// Over your weapon's rate of fire (`atk`), from your last shot, as RotMG plays it.
			k = FrameHalf(level.maptime - atkAt, atkMs > 0 ? atkMs : 300) ? 2 : 1;
		}
		else if (moving)
		{
			// RotMG: 3.5 / speed (tiles per ms) for the two frames.
			double tile = eye > 0 ? eye / (0.8 * 0.85) : 64;
			double tilesPerSec = walkSpeed > 0 ? walkSpeed / tile : 5;
			k = FrameHalf(level.maptime, int(3500 / tilesPerSec)) ? 4 : 3;
		}
		static const int BACK[] = { 9, 12, 13, 10, 11 };    // J; M, N; K, L
		static const int SIDE[] = { 0, 7, 8, 5, 6 };        // A; H, I; F, G
		t.frame = selfBack ? BACK[k] : SIDE[k];
		t.bSPRITEFLIP = false;
	}

	void SendThrow(PlayerInfo p)
	{
		if (!throwAim || p.mo == null)
		{
			return;
		}
		double d = ThrowDistance(thirdPerson ? throwPitch : p.mo.pitch);
		if (abs(d - throwSent) > 1 || level.maptime - throwSentAt >= RESEND_TICS)
		{
			throwSent = d;
			throwSentAt = level.maptime;
			RomtgBridge.Send(String.Format("throw %.1f", d));
		}
	}

	void SendFire(PlayerInfo p)
	{
		int fire = (p.cmd.buttons & BT_ATTACK) ? 1 : 0;
		int aim = int(p.mo.angle) % 360;
		if (fire != lastFire || aim != lastAim || level.maptime - lastFireAt >= RESEND_TICS)
		{
			lastFire = fire;
			lastAim = aim;
			lastFireAt = level.maptime;
			RomtgBridge.Send(String.Format("fire %d %.1f", fire, p.mo.angle));
		}
	}

	// Your RotMG weapon, big in the bottom right as if held. No Doom status bar: the launcher
	// sets screenblocks 12.
	// Doom's own menus never stay open: one (Esc, a function key) pauses Doom and dims it
	// nearly black, and stayed open behind the swaps, so first person showed only Doom's menu
	// on black from then on (a friend's game, 2026-11-15). The realm doesn't pause; Doom
	// mustn't either. Closed every tic.
	// RotMG's map filters for your status (gldefs.txt): blind almost black, drunk a pulsing blur
	// (20 + 10 sin(t) of RotMG's 600 pixels, Map.as), paused grey.
	ui void StatusShaders()
	{
		int want = 0;
		if (cond0 & COND_BLIND) want |= 1;
		if (cond0 & COND_DRUNK) want |= 2;
		if (cond0 & COND_PAUSED) want |= 4;
		if (want != shadersOn)
		{
			PPShader.SetEnabled("RomtgBlind", (want & 1) != 0);
			PPShader.SetEnabled("RomtgDrunk", (want & 2) != 0);
			PPShader.SetEnabled("RomtgPause", (want & 4) != 0);
			shadersOn = want;
		}
		if (want & 2)
		{
			double t = MSTimeF() / 1000.0;
			PPShader.SetUniform1f("RomtgDrunk", "radius", (20 + 10 * sin(t * 180.0 / M_PI)) / 600.0 / 2);
		}
	}

	override void UiTick()
	{
		StatusShaders();
		if (menuactive != Menu.Off)
		{
			for (int i = 0; i < 8; i++)
			{
				let m = Menu.GetCurrentMenu();
				if (m == null)
				{
					break;
				}
				m.Close();
			}
		}
	}

	override void RenderOverlay(RenderEvent e)
	{
		FrameStats();
		if (drawnGround != groundVersion)
		{
			drawnGround = groundVersion;
			double t0 = MSTimeF();
			DrawGround();
			groundDraws++;
			groundMax = max(groundMax, MSTimeF() - t0);
		}
		if (automapactive)
		{
			return;
		}
		DrawRealmHud(e);
		if (thirdPerson || weaponSprite.Length() == 0 || weaponSprite == "-")
		{
			return;
		}
		TextureID tex = TexMan.CheckForTexture(weaponSprite .. (weaponFrame == "B" ? "B0" : "A0"), TexMan.Type_Sprite);
		if (!tex.IsValid())
		{
			return;
		}
		double h = Screen.GetHeight() * 0.38;
		// A shot: the weapon thrusts forward (up and in, a little bigger) and settles back, over
		// at most the time to the next shot, so fast weapons pump and slow ones lunge.
		double kick = 0;
		double dur = min(atkTics, 12);
		double t = (level.maptime - atkAt + e.FracTic) / max(dur, 1.0);
		if (atkAt > 0 && t >= 0 && t < 1)
		{
			kick = t < 0.25 ? t / 0.25 : 1 - (t - 0.25) / 0.75;
		}
		// Each kind its own move. RotMG's weapon pictures lie diagonally, handle bottom left and
		// tip top right, so the picture turns about its handle (its bottom-left corner):
		// swords and katanas swing (tip down across the view and back), wands and staves flick,
		// bows draw (pulled back and down, swelling), daggers stab (straight in).
		int tw, th;
		[tw, th] = TexMan.GetSize(tex);
		double baseX = Screen.GetWidth() * 0.6, baseY = Screen.GetHeight() - h * 0.92;
		double angle = 0, scale = 1, dx = 0, dy = 0;
		switch (weaponSlot)
		{
		case 1: case 24:         // sword, katana: a swing across, the tip sweeping in towards the middle
			angle = 50 * kick; dx = -h * 0.18 * kick; dy = -h * 0.04 * kick;
			break;
		case 2:                  // dagger (rogue, assassin, trickster): a quicker, shorter swing,
			                     // not a stab (Ryan, 2026-11-15: it pulsed)
			angle = 40 * kick; dx = -h * 0.14 * kick; dy = -h * 0.03 * kick;
			break;
		case 8: case 17:         // wand, staff: flicked straight at the target, the tip going
			                     // forward (in and up, away from you), not to the side
			angle = 12 * kick; scale = 1 - 0.12 * kick; dx = -h * 0.10 * kick; dy = -h * 0.16 * kick;
			break;
		case 3:                  // bow: drawn back, swelling
			scale = 1 + 0.15 * kick; dx = h * 0.04 * kick; dy = h * 0.08 * kick;
			break;
		default:                 // the rest: a stab
			scale = 1 + 0.08 * kick; dx = -h * 0.10 * kick; dy = -h * 0.14 * kick;
			break;
		}
		double s = h * scale;
		// The handle (bottom left) stays put but for the move's own shift; the picture turns about it.
		Screen.DrawTexture(tex, false, baseX + dx, baseY + h + dy,
			DTA_DestWidthF, s, DTA_DestHeightF, s,
			DTA_LeftOffsetF, 0.0, DTA_TopOffsetF, double(th), DTA_Rotate, angle, DTA_FlipX, weaponFlip);
	}

	// ---------------------------------------------------------------- RotMG's HUD

	clearscope static int Hex(string text)
	{
		int v = 0;
		int n = text.Length();
		for (int i = 0; i < n; i++)
		{
			int c = text.ByteAt(i);
			int d = (c >= 48 && c <= 57) ? c - 48 : (c >= 97 && c <= 102) ? c - 87 : (c >= 65 && c <= 70) ? c - 55 : -1;
			if (d < 0) break;
			v = v * 16 + d;
		}
		return v;
	}

	ui void Text(Font f, double x, double y, string text, int rgb, double size, double alpha = 1)
	{
		// A dark copy first, as RotMG outlines its HUD text.
		Screen.DrawText(f, Font.CR_UNTRANSLATED, x + size, y + size, text, DTA_ScaleX, size, DTA_ScaleY, size,
			DTA_Color, 0xFF000000, DTA_Alpha, alpha * 0.8);
		Screen.DrawText(f, Font.CR_UNTRANSLATED, x, y, text, DTA_ScaleX, size, DTA_ScaleY, size,
			DTA_Color, 0xFF000000 | rgb, DTA_Alpha, alpha);
	}

	// RotMG's own HUD (gold and fame, boss bar, chat, the texts over you) is drawn by RotMG itself
	// in a see-through window over Doom (romtg/HudWindow.as). Here: what only Doom can draw,
	// because it is about Doom's 3D view: health bars at enemies' feet and which way the boss is.
	// And, after Tab, Doom greyed out with how to get back.
	ui void DrawRealmHud(RenderEvent e)
	{
		Font f = NewSmallFont;
		double w = Screen.GetWidth(), h = Screen.GetHeight();
		double size = max(1.0, h / 540.0);
		DrawNameTags(e, w, h, size);
		DrawFloatingTexts(e, w, h, size);
		DrawThrowArc(e, w, h, size);
		DrawSelfBar(e, w, h);
		if (hasQuest)
		{
			DrawQuestMarker(f, w, h * 0.105, size);   // a little lower: clear of the boss's icon (Ryan, 2026-11-21)
		}
		if (modalUp)
		{
			// A RotMG dialog over Doom (the potion storage...): grayed behind it as RotMG grays
			// its screen (DialogsView: 0x151515 at 0.6), no "press Tab" line over it.
			Screen.Dim(0x151515, 0.6, 0, 0, int(w), int(h));
		}
		else if (panel)
		{
			Screen.Dim(0, 0.45, 0, 0, int(w), int(h));
			string tell = "Press TAB to return to the game";
			double big = size * 1.5;
			Text(f, (w - f.StringWidth(tell) * big) / 2, h * 0.5, tell, 0xFFFFFF, big);
		}
	}

	// A thrown ability being aimed: its arc from your hand and a ring where it lands, the
	// size of what it does there (its radius), on the ground.
	ui void DrawThrowArc(RenderEvent e, double w, double h, double size)
	{
		PlayerInfo p = players[consoleplayer];
		if (!throwAim || p == null || p.mo == null || eye <= 0)
		{
			return;
		}
		double tile = eye / (0.8 * 0.85);
		double hfov = 2 * atan(tan(p.fov / 2) * (w / h) / (4.0 / 3.0));
		double focal = (w / 2) / tan(hfov / 2);
		double yaw = e.ViewAngle, pitch = e.ViewPitch;
		double d = ThrowDistance(thirdPerson ? throwPitch : pitch);
		double floorZ = p.mo.floorz + 0.5;
		// From you, not from the camera (in third person it's behind and above you).
		Vector3 me = p.mo.prev + (p.mo.pos - p.mo.prev) * e.FracTic;
		Vector3 from = (me.x + cos(yaw) * tile * 0.3, me.y + sin(yaw) * tile * 0.3, me.z + eye - tile * 0.25);
		Vector3 land = (me.x + cos(yaw) * d, me.y + sin(yaw) * d, floorZ);
		double peak = tile * 0.2 + d * 0.2;
		double thick = max(1.0, size * 1.5);
		int steps = 24;
		Vector2 last;
		bool had = false;
		for (int i = 0; i <= steps; i++)
		{
			double s = double(i) / steps;
			Vector3 pt = from + (land - from) * s;
			pt.z += 4 * peak * s * (1 - s);
			Vector2 sp;
			bool ok;
			[ok, sp] = ToScreen(pt, e, w, h, focal, yaw, pitch);
			if (ok && had && i > 1)
			{
				// Dashed, fading in from your hand.
				if (i % 2 == 0)
				{
					Screen.DrawThickLine(int(last.x), int(last.y), int(sp.x), int(sp.y), thick, 0xFFE680, int(255 * min(1.0, s * 3)));
				}
			}
			had = ok;
			last = sp;
		}
		double r = max(throwRadius, tile * 0.4);
		int around = 40;
		had = false;
		Vector2 first;
		bool firstOk = false;
		for (int i = 0; i <= around; i++)
		{
			double a = 360.0 * i / around;
			Vector3 pt = (land.x + cos(a) * r, land.y + sin(a) * r, floorZ);
			Vector2 sp;
			bool ok;
			[ok, sp] = ToScreen(pt, e, w, h, focal, yaw, pitch);
			if (ok && had)
			{
				Screen.DrawThickLine(int(last.x), int(last.y), int(sp.x), int(sp.y), thick, 0xFFB030, 230);
			}
			had = ok;
			last = sp;
		}
		// The spot itself: a small cross where it lands.
		Vector2 c;
		bool cok;
		[cok, c] = ToScreen(land, e, w, h, focal, yaw, pitch);
		if (cok)
		{
			double k = 6 * size;
			Screen.DrawThickLine(int(c.x - k), int(c.y), int(c.x + k), int(c.y), thick, 0xFFFFFF, 230);
			Screen.DrawThickLine(int(c.x), int(c.y - k * 0.6), int(c.x), int(c.y + k * 0.6), thick, 0xFFFFFF, 230);
		}
	}

	// Your health bar in third person, as RotMG draws it under a character: a dark 42x7 back
	// and a 40x5 bar going green to red, as wide as your character, just below your feet on
	// screen. Drawn every frame where you are drawn, so it stays put as you turn and move.
	ui void DrawSelfBar(RenderEvent e, double w, double h)
	{
		PlayerInfo p = players[consoleplayer];
		if (!thirdPerson || p == null || p.mo == null || eye <= 0 || selfId < 0
			|| selfId >= thingMax.Size() || thingMax[selfId] <= 0)
		{
			return;
		}
		double tile = eye / (0.8 * 0.85);
		double hfov = 2 * atan(tan(p.fov / 2) * (w / h) / (4.0 / 3.0));
		double focal = (w / 2) / tan(hfov / 2);
		double yaw = e.ViewAngle, pitch = e.ViewPitch;
		// Laid out on the screen against your picture as drawn there (at its depth, not the
		// bar's: measured at the bar's depth it came out wider than you), RotMG's way: the bar
		// SELF_BAR_GAP of your picture's height below its feet (RotMG: 4 px under a 40 px
		// figure), the green part as wide as your figure, the dark back round it.
		Vector3 me = p.mo.prev + (p.mo.pos - p.mo.prev) * e.FracTic;
		double cellW = selfWidth > 0 ? selfWidth : tile * 0.8;
		double cellH = selfHeight > 0 ? selfHeight : cellW;
		Vector2 feet, head;
		bool ok, ok2;
		[ok, feet] = ToScreen((me.x, me.y, p.mo.floorz), e, w, h, focal, yaw, pitch);
		[ok2, head] = ToScreen((me.x, me.y, p.mo.floorz + cellH), e, w, h, focal, yaw, pitch);
		Vector3 d = (me.x, me.y, p.mo.floorz + cellH / 2) - e.ViewPos;
		double depth = ViewDepth(d, yaw, pitch);
		if (!ok || !ok2 || depth < 4)
		{
			return;
		}
		double fw = cellW * SELF_BAR_WIDTH / depth * focal, fh = fw * 5.0 / 40.0;   // the green
		double bw = fw * 43.0 / 40.0, bh = fw * 8.0 / 40.0;                         // the back
		double x = feet.x - bw / 2, y = feet.y + (feet.y - head.y) * SELF_BAR_GAP;
		double frac = clamp(double(thingHp[selfId]) / thingMax[selfId], 0, 1);
		// Drawn over the 3D view, so what stands nearer the camera (your pet at your heels, a
		// player passing in front) is cut out of it, as it would hide a bar in the world (Ryan,
		// 2026-11-21: it showed over the pet).
		// Each solid pixel of what stands nearer the camera, as a rectangle on the screen.
		Array<double> rx0, ry0, rx1, ry1;
		Covers(e, me, depth, x, y, bw, bh, focal, yaw, pitch, w, h, rx0, ry0, rx1, ry1);
		// Drawn in slabs across the screen between the rectangles' edges: in each, the bar
		// minus the rectangles that span it, so only real pixels hide it, partly if partly.
		Array<double> xs;
		xs.Push(x);
		xs.Push(x + bw);
		for (int i = 0; i < rx0.Size(); i++)
		{
			xs.Push(rx0[i]);
			xs.Push(rx1[i]);
		}
		SortDoubles(xs);
		for (int s = 0; s + 1 < xs.Size(); s++)
		{
			double xa = max(xs[s], x), xb = min(xs[s + 1], x + bw);
			if (xb - xa < 0.01)
			{
				continue;
			}
			double xm = (xa + xb) / 2;
			Array<double> ya, yb;   // covered heights in this slab
			for (int i = 0; i < rx0.Size(); i++)
			{
				if (rx0[i] <= xm && rx1[i] >= xm)
				{
					ya.Push(ry0[i]);
					yb.Push(ry1[i]);
				}
			}
			// What of the bar's height isn't covered, top to bottom.
			double at = y;
			while (at < y + bh - 0.01)
			{
				double upto = y + bh;
				bool covered = false;
				for (int i = 0; i < ya.Size(); i++)
				{
					if (ya[i] <= at + 0.01 && yb[i] > at + 0.01)
					{
						covered = true;
						at = max(at, yb[i]);
					}
				}
				if (covered)
				{
					continue;
				}
				for (int i = 0; i < ya.Size(); i++)
				{
					if (ya[i] > at && ya[i] < upto)
					{
						upto = ya[i];
					}
				}
				int cx = int(xa + 0.5), cy = int(at + 0.5);
				int cw = int(xb + 0.5) - cx, chh = int(upto + 0.5) - cy;
				if (cw > 0 && chh > 0)
				{
					Screen.SetClipRect(cx, cy, cw, chh);
					Screen.Dim(0x111111, 0.85, int(x), int(y), max(1, int(bw)), max(1, int(bh)));
					if (frac > 0)
					{
						Screen.Dim(Green2Red(frac), 1.0, int(x + (bw - fw) / 2), int(y + (bh - fh) / 2), max(1, int(fw * frac)), max(1, int(fh)));
					}
					Screen.ClearClipRect();
				}
				at = upto;
			}
		}
	}

	ui static void SortDoubles(out Array<double> a)
	{
		for (int i = 1; i < a.Size(); i++)
		{
			double v = a[i];
			int j = i - 1;
			while (j >= 0 && a[j] > v)
			{
				a[j + 1] = a[j];
				j--;
			}
			a[j + 1] = v;
		}
	}

	clearscope static int HexDigit(int ch)
	{
		if (ch >= 48 && ch <= 57) return ch - 48;     // 0-9
		if (ch >= 97 && ch <= 102) return ch - 87;    // a-f
		return 0;
	}

	// The solid pixels of upright pictures standing nearer the camera than DEPTH, within a few
	// tiles of you (ME), that fall on the bar at X, Y (BW x BH): screen rectangles RX0..RX1 x
	// RY0..RY1. Each pixel placed as Doom draws it: pictures stand upright facing your view's
	// direction, a texel's corners projected like any point in the world (with the camera
	// tilted down their top and bottom are at different distances; a flat guess drifted by a
	// pixel at the feet, Ryan 2026-11-21).
	ui void Covers(RenderEvent e, Vector3 me, double depth, double x, double y, double bw, double bh,
		double focal, double yaw, double pitch, double w, double h,
		out Array<double> rx0, out Array<double> ry0, out Array<double> rx1, out Array<double> ry1)
	{
		double tile = eye / (0.8 * 0.85);
		Vector3 right = (sin(yaw), -cos(yaw), 0);   // the screen's right, in the world
		double meAhead = (me.x - e.ViewPos.x) * cos(yaw) + (me.y - e.ViewPos.y) * sin(yaw);   // your plane
		for (int i = 0; i < things.Size(); i++)
		{
			Actor t = things[i];
			if (t == null || i == selfId || t is "RomtgWall" || t.bFLATSPRITE || t.bINVISIBLE
				|| (t.GetRenderStyle() == STYLE_Translucent && t.alpha < 0.3))
			{
				continue;
			}
			Vector3 at = t.prev + (t.pos - t.prev) * e.FracTic;
			if ((at.xy - me.xy).Length() > tile * 4)
			{
				continue;
			}
			// Pictures stand upright facing the view's direction, so which of two is in front is
			// which plane is nearer along it: their middles' depths differ with their heights
			// (a cactus hugged by you counted as behind you, so it didn't hide your bar; Ryan,
			// 2026-11-21).
			Vector3 d = at - e.ViewPos;
			double tdepth = ViewDepth(d, yaw, pitch);
			if (tdepth < 4 || d.x * cos(yaw) + d.y * sin(yaw) >= meAhead)
			{
				continue;
			}
			TextureID tex;
			bool flip;
			Vector2 sc;
			[tex, flip, sc] = t.CurState.GetSpriteTexture(0, 0, (0, 0), t.sprite, t.frame);
			if (!tex.IsValid())
			{
				continue;
			}
			Vector2 size = TexMan.GetScaledSize(tex);
			Vector2 off = TexMan.GetScaledOffset(tex);
			String m = spriteMask.GetIfExists(TexMan.GetName(tex));
			Array<String> f;
			m.Split(f, " ");
			int tw = f.Size() >= 3 ? f[0].ToInt() : 1;
			int th = f.Size() >= 3 ? f[1].ToInt() : 1;
			string hex = f.Size() >= 3 ? f[2] : "8";   // no mask: one solid block
			double texW = size.x / tw, texH = size.y / th;   // a mask pixel, in texture units
			bool mirror = flip != t.bSPRITEFLIP;
			// The picture's whole rectangle first: nothing to do if it misses the bar.
			Vector2 a, b;
			bool oka, okb;
			[oka, a] = ToScreen(at + right * (-off.x * t.scale.x) + (0, 0, off.y * t.scale.y), e, w, h, focal, yaw, pitch);
			[okb, b] = ToScreen(at + right * ((size.x - off.x) * t.scale.x) + (0, 0, (off.y - size.y) * t.scale.y), e, w, h, focal, yaw, pitch);
			if (!oka || !okb || max(a.x, b.x) < x || min(a.x, b.x) > x + bw || max(a.y, b.y) < y || min(a.y, b.y) > y + bh)
			{
				continue;
			}
			for (int r = 0; r < th; r++)
			{
				for (int c = 0; c < tw; c++)
				{
					int col = mirror ? tw - 1 - c : c;
					int bit = r * tw + col;
					if (bit / 4 >= int(hex.Length()) || (HexDigit(hex.ByteAt(bit / 4)) & (8 >> (bit % 4))) == 0)
					{
						continue;
					}
					// This pixel's four corners on the screen (its sides lean a little with the
					// camera tilted, so two corners alone left slivers between neighbours that
					// the bar showed through; Ryan, 2026-11-21), and a hair round them.
					double xl = (c * texW - off.x) * t.scale.x, xr = ((c + 1) * texW - off.x) * t.scale.x;
					double zt = (off.y - r * texH) * t.scale.y, zb = (off.y - (r + 1) * texH) * t.scale.y;
					Vector2 p0, p1, p2, p3;
					bool ok0, ok1, ok2, ok3;
					[ok0, p0] = ToScreen(at + right * xl + (0, 0, zt), e, w, h, focal, yaw, pitch);
					[ok1, p1] = ToScreen(at + right * xr + (0, 0, zt), e, w, h, focal, yaw, pitch);
					[ok2, p2] = ToScreen(at + right * xl + (0, 0, zb), e, w, h, focal, yaw, pitch);
					[ok3, p3] = ToScreen(at + right * xr + (0, 0, zb), e, w, h, focal, yaw, pitch);
					if (!ok0 || !ok1 || !ok2 || !ok3)
					{
						continue;
					}
					double x0 = min(min(p0.x, p1.x), min(p2.x, p3.x)) - 0.35, x1 = max(max(p0.x, p1.x), max(p2.x, p3.x)) + 0.35;
					double y0 = min(min(p0.y, p1.y), min(p2.y, p3.y)) - 0.35, y1 = max(max(p0.y, p1.y), max(p2.y, p3.y)) + 0.35;
					if (x1 < x || x0 > x + bw || y1 < y || y0 > y + bh)
					{
						continue;
					}
					rx0.Push(x0);
					ry0.Push(y0);
					rx1.Push(x1);
					ry1.Push(y1);
				}
			}
		}
		// Walls are boxes, not pictures: for each screen pixel of the bar, whether the line from
		// the camera through it meets a nearby box before the bar's depth (Ryan, 2026-11-21: the
		// bar showed through walls). Runs of covered pixels down a column become one rectangle.
		Array<RomtgWall> boxes;
		for (int i = 0; i < things.Size(); i++)
		{
			let wall = RomtgWall(things[i]);
			if (wall == null)
			{
				continue;
			}
			double dist = (wall.pos.xy - me.xy).Length();
			if (dist < tile * 5 + wall.boxHalf)
			{
				boxes.Push(wall);
			}
		}
		if (boxes.Size() == 0)
		{
			return;
		}
		// In Doom's stretched space (heights times the pixel ratio, ToScreen), where the screen's
		// lines are straight.
		double ps = level.pixelstretch;
		double rp = RenderPitch(pitch);
		Vector3 fwdV = (cos(rp) * cos(yaw), cos(rp) * sin(yaw), -sin(rp));
		Vector3 upV = (sin(rp) * cos(yaw), sin(rp) * sin(yaw), cos(rp));
		Vector3 eyeS = (e.ViewPos.x, e.ViewPos.y, e.ViewPos.z * ps);
		for (int px = int(floor(x)); px < int(ceil(x + bw)); px++)
		{
			int runFrom = -1;
			int pyEnd = int(ceil(y + bh));
			for (int py = int(floor(y)); py <= pyEnd; py++)
			{
				bool hit = false;
				if (py < pyEnd)
				{
					// The line through this pixel's middle, one unit of depth per unit of T.
					Vector3 dir = fwdV + right * ((px + 0.5 - w / 2) / focal) + upV * ((h / 2 - (py + 0.5)) / focal);
					for (int k = 0; k < boxes.Size() && !hit; k++)
					{
						Vector3 b = boxes[k].pos;
						double half = boxes[k].boxHalf > 0 ? boxes[k].boxHalf : tile / 2;
						double tall = boxes[k].boxHeight > 0 ? boxes[k].boxHeight : tile;
						hit = RayHitsBox(eyeS, dir, (b.x, b.y, b.z * ps), half, tall * ps, depth);
					}
				}
				if (hit && runFrom < 0)
				{
					runFrom = py;
				}
				else if (!hit && runFrom >= 0)
				{
					rx0.Push(px);
					ry0.Push(runFrom);
					rx1.Push(px + 1);
					ry1.Push(py);
					runFrom = -1;
				}
			}
		}
	}

	// Whether the line FROM + DIR * t, 0 < t < UPTO, goes through the box BOX +- HALF across,
	// BOX.z .. BOX.z + HEIGHT up (slabs).
	clearscope static bool RayHitsBox(Vector3 from, Vector3 dir, Vector3 box, double half, double height, double upto)
	{
		double t0 = 0, t1 = upto;
		for (int axis = 0; axis < 3; axis++)
		{
			double o = axis == 0 ? from.x : axis == 1 ? from.y : from.z;
			double v = axis == 0 ? dir.x : axis == 1 ? dir.y : dir.z;
			double lo = axis == 0 ? box.x - half : axis == 1 ? box.y - half : box.z;
			double hi = axis == 0 ? box.x + half : axis == 1 ? box.y + half : box.z + height;
			if (abs(v) < 1e-9)
			{
				if (o < lo || o > hi) return false;
				continue;
			}
			double a = (lo - o) / v, b = (hi - o) / v;
			if (a > b) { double tmp = a; a = b; b = tmp; }
			t0 = max(t0, a);
			t1 = min(t1, b);
			if (t0 > t1) return false;
		}
		return true;
	}

	// RotMG's health colour (Character.green2redu): green when full, through yellow, to red.
	clearscope static Color Green2Red(double frac)
	{
		int r = frac >= 0.5 ? int(255 * (1 - frac) * 2) : 255;
		int g = frac >= 0.5 ? 255 : int(255 * frac * 2);
		return Color(255, r, g, 0);
	}

	// A point in the world on the screen (as DrawNameTags projects), and whether it's in front.
	// A point in the world on the screen, exactly as Doom's renderer projects it
	// (hw_drawinfo.cpp, r_utility.cpp): the world's heights stretched by the level's pixel
	// ratio before turning to the view, and the view's pitch adjusted for that stretch. (Doom
	// sprites stand upright; projecting as if the stretch came after put their pixels a little
	// off from where Doom draws them, so the bar's cut-outs missed; Ryan, 2026-11-21.)
	ui bool, Vector2 ToScreen(Vector3 pt, RenderEvent e, double w, double h, double focal, double yaw, double pitch)
	{
		Vector3 d = pt - e.ViewPos;
		d.z *= level.pixelstretch;
		double rp = RenderPitch(pitch);
		double fwd = d.x * cos(yaw) + d.y * sin(yaw);
		double right = d.x * sin(yaw) - d.y * cos(yaw);
		double depth = fwd * cos(rp) - d.z * sin(rp);
		double up = fwd * sin(rp) + d.z * cos(rp);
		if (depth < 4)
		{
			return false, (0, 0);
		}
		return true, (w / 2 + right / depth * focal, h / 2 - up / depth * focal);
	}

	// The pitch Doom renders with for a look PITCH: tan stretched by the pixel ratio.
	clearscope static double RenderPitch(double pitch)
	{
		return atan2(sin(pitch) * level.pixelstretch, cos(pitch));
	}

	// How far in front of the camera D (from it) is, as ToScreen measures it.
	clearscope static double ViewDepth(Vector3 d, double yaw, double pitch)
	{
		double rp = RenderPitch(pitch);
		return (d.x * cos(yaw) + d.y * sin(yaw)) * cos(rp) - d.z * level.pixelstretch * sin(rp);
	}

	// RotMG's status texts over things (the damage you do, mostly): over the thing's head,
	// rising and fading in a second as in RotMG, and drawn over everything, as RotMG draws them.
	ui void DrawFloatingTexts(RenderEvent e, double w, double h, double size)
	{
		PlayerInfo p = players[consoleplayer];
		if (p == null || eye <= 0 || floatAt.Size() == 0)
		{
			return;
		}
		double tile = eye / (0.8 * 0.85);   // eye = tile * 0.8 * 0.85 (bridge.py)
		// Doom's horizontal field of view, widened for the screen's shape as Doom does.
		double hfov = 2 * atan(tan(p.fov / 2) * (w / h) / (4.0 / 3.0));
		double focal = (w / 2) / tan(hfov / 2);
		double yaw = e.ViewAngle, pitch = e.ViewPitch;
		Font f = NewSmallFont;
		for (int i = 0; i < floatAt.Size(); i++)
		{
			double age = clamp((level.maptime - floatAt[i] + e.FracTic) / FLOAT_TICS, 0, 1);
			// Over the head (HeadOf), rising: where the thing is drawn this frame (between its
			// last two places, as Doom draws it) while it's there, else where it was last seen.
			// From its tic place only, it lagged and jumped after a moving thing (your own, in
			// third person; Ryan, 2026-11-21).
			double head = floatZ[i] + tile * (0.15 + 0.6 * age);
			Vector2 at = (floatX[i], floatY[i]);
			Actor ft = i < floatThing.Size() ? floatThing[i] : null;
			if (ft != null)
			{
				Vector3 now = ft.prev + (ft.pos - ft.prev) * e.FracTic;
				at = now.xy;
				head += now.z - ft.pos.z;
			}
			Vector3 d = (at.x, at.y, head) - e.ViewPos;
			double fwd = d.x * cos(yaw) + d.y * sin(yaw);
			double right = d.x * sin(yaw) - d.y * cos(yaw);
			double depth = fwd * cos(pitch) - d.z * sin(pitch);
			double up = fwd * sin(pitch) + d.z * cos(pitch);
			if (depth < 8)
			{
				continue;
			}
			double sx = w / 2 + right / depth * focal;
			double sy = h / 2 - up / depth * focal * level.pixelstretch;   // (see DrawNameTags)
			// As big as RotMG's (about half a tile high) up close, never too small to read.
			double big = clamp(tile * 0.45 / depth * focal / f.GetHeight(), size * 0.9, size * 3);
			string text = floatText[i];
			double tw = f.StringWidth(text) * big;
			if (sx + tw < 0 || sx - tw > w || sy < 0 || sy > h)
			{
				continue;
			}
			double alpha = age < 0.6 ? 1.0 : (1 - age) / 0.4;
			Text(f, sx - tw / 2, sy - f.GetHeight() * big, text, floatColor[i], big, alpha);
		}
	}

	// Other players' names over their heads, as RotMG labels them (its colours), sized like
	// RotMG's against a figure, readable from afar, and fading into the fog with them.
	ui void DrawNameTags(RenderEvent e, double w, double h, double size)
	{
		PlayerInfo p = players[consoleplayer];
		if (p == null || eye <= 0 || nameText.Size() == 0)
		{
			return;
		}
		double tile = eye / (0.8 * 0.85);
		double hfov = 2 * atan(tan(p.fov / 2) * (w / h) / (4.0 / 3.0));
		double focal = (w / 2) / tan(hfov / 2);
		double yaw = e.ViewAngle, pitch = e.ViewPitch;
		Font f = NewSmallFont;
		for (int i = 0; i < nameText.Size() && i < things.Size(); i++)
		{
			Actor t = things[i];
			if (t == null || nameText[i].Length() == 0)
			{
				continue;
			}
			double alpha = t.GetRenderStyle() == STYLE_Translucent ? t.alpha : 1.0;
			if (alpha <= 0.02)
			{
				continue;
			}
			// Where Doom draws it this frame: between its last two places (as Doom interpolates
			// things), not where it will be at the next tic (a moving player's tag led him).
			Vector3 now = t.prev + (t.pos - t.prev) * e.FracTic;
			Vector3 d = (now.x, now.y, HeadOf(t) + tile * 0.12) - e.ViewPos;
			double fwd = d.x * cos(yaw) + d.y * sin(yaw);
			double right = d.x * sin(yaw) - d.y * cos(yaw);
			double depth = fwd * cos(pitch) - d.z * sin(pitch);
			double up = fwd * sin(pitch) + d.z * cos(pitch);
			if (depth < 8)
			{
				continue;
			}
			double sx = w / 2 + right / depth * focal;
			// Doom stretches its view up and down (pixel ratio, 1.2 as Doom's 320x200 had it).
			double sy = h / 2 - up / depth * focal * level.pixelstretch;
			double big = clamp(tile * 0.3 / depth * focal / f.GetHeight(), size * 0.8, size * 2);
			double tw = f.StringWidth(nameText[i]) * big;
			if (sx + tw < 0 || sx - tw > w || sy < 0 || sy > h)
			{
				continue;
			}
			Text(f, sx - tw / 2, sy - f.GetHeight() * big, nameText[i], nameColor[i], big, alpha);
		}
	}

	// Where the boss is from where you look: a marker under the bar when it's ahead, an arrow at
	// the side when it isn't, and how many tiles away.
	ui void DrawQuestMarker(Font f, double w, double y, double size)
	{
		PlayerInfo p = players[consoleplayer];
		if (p == null || p.mo == null || eye <= 0)
		{
			return;
		}
		Vector2 to = questPos - p.mo.pos.xy;
		double rel = Actor.DeltaAngle(p.mo.angle, atan2(to.y, to.x));   // + is to your left
		double half = p.fov / 2;
		double tiles = to.Length() / (eye / (0.8 * 0.85));   // eye = tile * 0.8 * 0.85
		string dist = String.Format("%d", int(tiles + 0.5));
		string mark;
		double x;
		if (abs(rel) < half)
		{
			x = w / 2 - tan(rel) / tan(half) * (w / 2);
			mark = "v";
		}
		else
		{
			x = rel > 0 ? 30 * size : w - 30 * size;
			mark = rel > 0 ? "<" : ">";
		}
		double big = size * 2;
		Text(f, x - f.StringWidth(mark) * big / 2, y, mark, 0xFF4040, big);
		Text(f, x - f.StringWidth(dist) * size / 2, y + f.GetHeight() * big, dist, 0xFFB0B0, size);
	}

	void AddChat(string rest)
	{
		// rest: "NC TC NAME<tab>TO<tab>TEXT"
		Array<string> head;
		rest.Split(head, " ", TOK_KEEPEMPTY);
		if (head.Size() < 3) return;
		int skip = head[0].Length() + head[1].Length() + 2;
		Array<string> parts;
		rest.Mid(skip).Split(parts, "\t", TOK_KEEPEMPTY);
		if (parts.Size() < 3) return;
		string who = parts[0];
		if (parts[1].Length() > 0) who = who .. " > " .. parts[1];
		chatName.Push(who);
		chatText.Push(parts[2]);
		chatNameColor.Push(Hex(head[0]) == 0 ? 0x30FF30 : Hex(head[0]));
		chatColor.Push(Hex(head[1]) == 0 ? 0xFFFFFF : Hex(head[1]));
		chatAt.Push(level.maptime);
		while (chatText.Size() > 40)
		{
			chatName.Delete(0); chatText.Delete(0); chatNameColor.Delete(0); chatColor.Delete(0); chatAt.Delete(0);
		}
	}

	void SendMove(PlayerInfo p)
	{
		Vector2 dir = InputDir(p);
		if (dir.x != lastMove.x || dir.y != lastMove.y || level.maptime - lastMoveAt >= RESEND_TICS)
		{
			lastMove = dir;
			lastMoveAt = level.maptime;
			RomtgBridge.Send(String.Format("m %.4f %.4f", dir.x, dir.y));
		}
	}

	void Handle(string line, Actor mo)
	{
		if (line.Left(5) == "chat ")
		{
			AddChat(line.Mid(5));
			return;
		}
		if (line.Left(3) == "ds ")
		{
			// ds ID COLOR TEXT
			int s1 = line.IndexOf(" ", 3);
			int s2 = s1 > 3 ? line.IndexOf(" ", s1 + 1) : -1;
			int id = s1 > 3 ? line.Mid(3, s1 - 3).ToInt() : -1;
			// Only where RotMG would show it to you: on its screen (about DAMAGE_TILES round you)
			// and in sight, not behind walls. Over Doom's 48 tiles of sight, other players' hits
			// on far enemies showed far off, drawn over everything (Ryan, 2026-11-16).
			PlayerPawn me = players[consoleplayer].mo;
			double tileSize = eye / (0.8 * 0.85);
			bool near = s2 > s1 && id >= 0 && id < things.Size() && things[id] != null && me != null
				&& (eye <= 0 || (things[id].pos.xy - me.pos.xy).Length() <= DAMAGE_TILES * tileSize)
				&& me.CheckSight(things[id], SF_IGNOREVISIBILITY);
			if (near)
			{
				Actor t = things[id];
				floatThing.Push(t);
				floatX.Push(t.pos.x);
				floatY.Push(t.pos.y);
				floatZ.Push(TextBase(t));
				floatColor.Push(Hex(line.Mid(s1 + 1, s2 - s1 - 1)));
				floatText.Push(line.Mid(s2 + 1));
				floatAt.Push(level.maptime);
				while (floatAt.Size() > 60)
				{
					DeleteFloat(0);
				}
			}
			return;
		}
		if (line.Left(3) == "st ")
		{
			int space = line.IndexOf(" ", 3);
			if (space > 3)
			{
				statusColor.Push(Hex(line.Mid(3, space - 3)));
				statusText.Push(line.Mid(space + 1));
				statusAt.Push(level.maptime);
				while (statusText.Size() > 8)
				{
					statusText.Delete(0); statusColor.Delete(0); statusAt.Delete(0);
				}
			}
			return;
		}
		Array<string> a;
		line.Split(a, " ");
		if (a.Size() == 0)
		{
			return;
		}
		string c = a[0];
		if (c == "ctl" && a.Size() >= 2)
		{
			control = a[1] == "1";
		}
		else if (c == "cam" && a.Size() >= 2)
		{
			bool on = a[1] == "1";
			if (on && !thirdPerson)
			{
				mo.pitch = CAM_PITCH;   // looking down at yourself
				throwPitch = (CAM_PITCH_MIN + CAM_PITCH_MAX) / 2;
			}
			else if (!on && thirdPerson)
			{
				mo.pitch = 0;
			}
			thirdPerson = on;
		}
		else if (c == "selfid" && a.Size() >= 2)
		{
			selfId = a[1].ToInt();
			selfBack = a.Size() >= 3 && a[2] == "1";
			selfWidth = a.Size() >= 4 ? a[3].ToDouble() : 0;
			selfHeight = a.Size() >= 5 ? a[4].ToDouble() : 0;
		}
		else if (c == "throwaim" && a.Size() >= 2)
		{
			throwAim = a[1] == "1";
			if (throwAim && a.Size() >= 4)
			{
				throwMax = a[2].ToDouble();
				throwRadius = a[3].ToDouble();
			}
			throwSent = -1;
		}
		else if (c == "cond" && a.Size() >= 3)
		{
			cond0 = a[1].ToInt();
			cond1 = a[2].ToInt();
		}
		else if (c == "spd" && a.Size() >= 2)
		{
			walkSpeed = a[1].ToDouble();
		}
		else if (c == "push" && a.Size() >= 3)
		{
			walkPush = (a[1].ToDouble(), a[2].ToDouble());
		}
		else if (c == "grid" && a.Size() >= 5)
		{
			gridAt = (a[1].ToDouble(), a[2].ToDouble());
			gridR = a[3].ToInt();
			string cells = a[4];
			gridCells.Clear();
			for (int i = 0; i < cells.Length(); i++)
			{
				gridCells.Push(cells.ByteAt(i) - 48);
			}
		}
		else if (c == "p" && a.Size() >= 3)
		{
			statPLines++;
			lastReportAt = level.maptime;
			Vector3 to = (a[1].ToDouble(), a[2].ToDouble(), mo.floorz);
			Vector2 last = pathX.Size() > 0 ? (pathX[pathX.Size() - 1], pathY[pathY.Size() - 1]) : mo.pos.xy;
			if ((to.xy - last).Length() > max(eye, 64) * 4)
			{
				mo.TeleportMove(to, false);   // a jump (a new map, a teleport): no sweep of the view
				pathT.Clear(); pathX.Clear(); pathY.Clear();
				replaying = false;
			}
			else if (a.Size() >= 4)
			{
				double t = a[3].ToDouble();
				int n = pathT.Size();
				if (n > 0 && t - pathT[n - 1] > 0 && t - pathT[n - 1] < REPLAY_GAP)
				{
					double gap = t - pathT[n - 1];
					reportEvery = reportEvery <= 0 ? gap : reportEvery + (gap - reportEvery) * 0.1;
				}
				if (n > 0 && t - pathT[n - 1] > REPLAY_GAP)
				{
					// Moving again after a stop: you left where you stood one report before
					// this one, not slowly over the whole time you stood there.
					pathT.Push(t - 17);
					pathX.Push(pathX[n - 1]);
					pathY.Push(pathY[n - 1]);
				}
				pathT.Push(t);
				pathX.Push(to.x);
				pathY.Push(to.y);
				while (pathT.Size() > 24)
				{
					pathT.Delete(0); pathX.Delete(0); pathY.Delete(0);
				}
			}
			else
			{
				mo.SetOrigin(to, true);
			}
			mo.vel.xy = (0, 0);
		}
		else if (c == "f" && a.Size() == 6)
		{
			// A ground tile: into the floor.
			int id = a[1].ToInt();
			Put(id, null);
			SetGround(id, 1, a[2].ToDouble(), a[3].ToDouble(), a[4], 0);
		}
		else if (c == "f" && a.Size() >= 7)
		{
			// Something lying on the ground (a rug...): a flat sprite just over it.
			double z = a[6].ToDouble();
			Actor t = Actor.Spawn("RomtgFlat", (a[2].ToDouble(), a[3].ToDouble(), z));
			RomtgPiece.Dress(t, a[4], a[5].ToDouble());
			Put(a[1].ToInt(), t);
		}
		else if (c == "fc" && a.Size() >= 6)
		{
			// Past RotMG's own sight: one plain colour per tile, as on RotMG's minimap (the
			// ground, and walls, trees... over it), into the floor.
			int id = a[1].ToInt();
			Put(id, null);
			SetGround(id, a.Size() >= 7 ? 3 : 2, a[2].ToDouble(), a[3].ToDouble(), "", Hex(a[4]));
		}
		else if (c == "hp" && a.Size() >= 4)
		{
			int id = a[1].ToInt();
			if (id >= 0 && id < 1000000)
			{
				if (id >= thingHp.Size())
				{
					thingHp.Resize(id + 1);
					thingMax.Resize(id + 1);
				}
				thingHp[id] = a[2].ToInt();
				thingMax[id] = a[3].ToInt();
				SetBar(id);
			}
		}
		else if (c == "look" && a.Size() >= 3)
		{
			// look ANGLE PITCH: turn your view (for tests: scripts can't move the mouse).
			mo.angle = a[1].ToDouble();
			mo.pitch = a[2].ToDouble();
		}
		else if (c == "fx" && a.Size() >= 4)
		{
			int id = a[1].ToInt();
			if (a[2] == "fountain" && id >= 0 && id < things.Size() && things[id] != null)
			{
				fxThing.Push(things[id]);
				fxColor.Push(Hex(a[3]));
			}
		}
		else if (c == "ef" && a.Size() >= 13)
		{
			ShowEffect(mo, a[1].ToInt(), (a[2].ToDouble(), a[3].ToDouble()), (a[4].ToDouble(), a[5].ToDouble()),
				(a[6].ToDouble(), a[7].ToDouble()), a[8].ToDouble(), a[9].ToDouble(), Hex(a[10]), a[11].ToDouble(), a[12] == "1");
		}
		else if (c == "heal" && a.Size() >= 3)
		{
			int id = a[1].ToInt();
			bool on = a[2] == "1";
			if (id < 0)
			{
				meHealing = on;
			}
			else if (id < 1000000)
			{
				if (id >= healing.Size())
				{
					healing.Resize(id + 1);
				}
				healing[id] = on;
			}
		}
		else if (c == "nm" && a.Size() >= 4)
		{
			int id = a[1].ToInt();
			if (id >= 0 && id < 1000000)
			{
				if (id >= nameText.Size())
				{
					nameText.Resize(id + 1);
					nameColor.Resize(id + 1);
				}
				string tagText = a[3];
				tagText.Replace("_", " ");
				nameText[id] = tagText;
				nameColor[id] = Hex(a[2]);
			}
		}
		else if (c == "bu" && a.Size() >= 10)
		{
			// bu X Y Z N SIZE VX VY SPREAD RGB,RGB...: RotMG's hit and death bursts (HitEffect,
			// ExplosionEffect): N dots of those colours flying off at VX, VY (+- SPREAD) units a
			// second for 200-300 ms. SIZE: the thing's size, a size-100 dot about a tenth of it.
			Array<string> colors;
			a[9].Split(colors, ",");
			Vector3 at = (a[1].ToDouble(), a[2].ToDouble(), a[3].ToDouble());
			int n = min(a[4].ToInt(), 12);
			double dotSize = max(2.0, a[5].ToDouble() * 0.1);
			double vx = a[6].ToDouble() / 35.0, vy = a[7].ToDouble() / 35.0, spread = a[8].ToDouble() / 35.0;
			for (int i = 0; i < n && colors.Size() > 0; i++)
			{
				let dotActor = RomtgDrop(Actor.Spawn("RomtgDrop", at));
				if (dotActor != null)
				{
					dotActor.Start(Hex(colors[random(0, colors.Size() - 1)]), dotSize, random(7, 10),
						(vx + frandom(-spread, spread), vy + frandom(-spread, spread), 0), 0);
					drops.Push(dotActor);
				}
			}
		}
		else if (c == "an" && a.Size() >= 4)
		{
			int id = a[1].ToInt();
			if (id >= 0 && id < 1000000)
			{
				if (id >= animAct.Size())
				{
					int was = animAct.Size();
					animAct.Resize(id + 1);
					animSince.Resize(id + 1);
					animYaw.Resize(id + 1);
					animMs.Resize(id + 1);
					for (int k = was; k <= id; k++) animAct[k] = -1;
				}
				int act = a[2].ToInt();
				if (act != animAct[id])
				{
					animSince[id] = level.maptime;
				}
				animAct[id] = act;
				animYaw[id] = a[3].ToDouble();
				animMs[id] = a.Size() >= 5 ? a[4].ToInt() : 0;
			}
		}
		else if (c == "sa" && a.Size() >= 5)
		{
			int id = a[1].ToInt();
			if (id >= 0 && id < 1000000)
			{
				if (id >= shotAimed.Size())
				{
					shotAimed.Resize(id + 1);
					shotYaw.Resize(id + 1);
					shotTex.Resize(id + 1);
					shotSpin.Resize(id + 1);
				}
				shotAimed[id] = true;
				shotYaw[id] = a[2].ToDouble();
				shotTex[id] = a[3].ToDouble();
				shotSpin[id] = a[4].ToDouble();
				if (id < things.Size() && things[id] != null)
				{
					things[id].bROLLSPRITE = true;
					things[id].bROLLCENTER = true;
				}
			}
		}
		else if (c == "tr" && a.Size() >= 5)
		{
			int id = a[1].ToInt();
			if (id >= 0 && id < 1000000)
			{
				if (id >= trailTics.Size())
				{
					trailTics.Resize(id + 1);
					trailColor.Resize(id + 1);
					trailShare.Resize(id + 1);
				}
				trailColor[id] = Hex(a[2]);
				trailTics[id] = max(1, int(a[3].ToDouble() * 35 / 1000));
				double intensity = a[4].ToDouble();
				bool mine = a.Size() >= 6 && a[5] == "1";
				// RotMG (Projectile.draw): yours always; others' at INTENSITY % (as its code reads).
				trailShare[id] = mine || intensity < 0 ? 1.0 : clamp(intensity / 100.0, 0.0, 1.0);
			}
		}
		else if (c == "fa" && a.Size() >= 5)
		{
			int id = a[1].ToInt();
			if (id >= 0 && id < gAnim.Size() && gKind[id] == 1)
			{
				gAnim[id] = a[2] == "wave" ? 2 : 1;
				gDx[id] = a[3].ToDouble();
				gDy[id] = a[4].ToDouble();
				groundVersion++;
				if (animLogged < 3)
				{
					animLogged++;
					Console.PrintfEx(PRINT_HIGH | PRINT_NONOTIFY, "[romtg] moving ground %d: %s %.3f %.3f", id, a[2], gDx[id], gDy[id]);
				}
			}
		}
		else if (c == "sink" && a.Size() >= 2)
		{
			sinking = a[1] == "1";
		}
		else if (c == "bgt" && a.Size() >= 2)
		{
			bgSprite = a[1];
			groundVersion++;
		}
		else if (c == "atk" && a.Size() >= 2)
		{
			atkAt = level.maptime;
			atkMs = a[1].ToInt();
			atkTics = max(3, int(a[1].ToInt() * 35 / 1000));
		}
		else if (c == "bg" && a.Size() >= 2)
		{
			SetBackground(Hex(a[1]));
		}
		else if (c == "panel" && a.Size() >= 2)
		{
			panel = a[1] == "1";
		}
		else if (c == "modal" && a.Size() >= 2)
		{
			modalUp = a[1] == "1";
		}
		else if (c == "b" && a.Size() >= 7)
		{
			Actor t = Actor.Spawn("RomtgBillboard", (a[2].ToDouble(), a[3].ToDouble(), a[4].ToDouble()));
			RomtgPiece.Dress(t, a[5], a[6].ToDouble());
			Put(a[1].ToInt(), t);
		}
		else if (c == "w" && a.Size() >= 8)
		{
			// A hair above the floor, so its sides never dip under the ground tiles (z 0.3).
			let w = RomtgWall(Actor.Spawn("RomtgWall", (a[2].ToDouble(), a[3].ToDouble(), 0.5)));
			w.Build(a[4].ToDouble(), a[5], a[6], a[7].ToDouble(), a.Size() >= 9 ? a[8].ToDouble() : 0);
			Put(a[1].ToInt(), w);
		}
		else if (c == "mv" && a.Size() >= 5)
		{
			int id = a[1].ToInt();
			if (id >= 0 && id < things.Size() && things[id] != null)
			{
				let w = RomtgWall(things[id]);
				if (w != null)
				{
					// A 3D object that moves: the whole box moves, at its own height.
					w.MoveBy((a[2].ToDouble(), a[3].ToDouble()) - w.pos.xy);
				}
				else
				{
					// A small step slides (smooth between tics); a jump (an enemy teleporting) doesn't
					// sweep across the screen for a frame.
					Vector3 to = (a[2].ToDouble(), a[3].ToDouble(), a[4].ToDouble());
					double jump = eye > 0 ? 2 * eye / (0.8 * 0.85) : 128;
					things[id].SetOrigin(to, (to.xy - things[id].pos.xy).Length() < jump);
				}
			}
		}
		else if (c == "scale" && a.Size() >= 3)
		{
			eye = a[2].ToDouble();
			double tileSize = a[1].ToDouble();
			if (tileSize > 1)
			{
				for (int i = 0; i < level.sectors.Size(); i++)
				{
					level.sectors[i].SetXScale(Sector.floor, CELL_PX / tileSize);
					level.sectors[i].SetYScale(Sector.floor, CELL_PX / tileSize);
				}
			}
			groundVersion++;
			let pp = PlayerPawn(mo);
			if (pp != null && eye > 4)
			{
				pp.ViewHeight = eye;
				if (pp.player != null) pp.player.viewheight = eye;
			}
		}
		else if (c == "quest")
		{
			hasQuest = a.Size() >= 6;
			if (hasQuest)
			{
				questPos = (a[1].ToDouble(), a[2].ToDouble());
				questHp = a[3].ToInt();
				questMax = a[4].ToInt();
				questName = a[5];
				for (int i = 6; i < a.Size(); i++) questName = questName .. " " .. a[i];
			}
		}
		else if (c == "cash" && a.Size() >= 3)
		{
			gold = a[1].ToInt();
			fame = a[2].ToInt();
		}
		else if (c == "weapon" && a.Size() >= 2)
		{
			weaponSprite = a[1];
			weaponPx = a.Size() >= 3 ? a[2].ToInt() : 8;
			weaponSlot = a.Size() >= 4 ? a[3].ToInt() : 0;
			weaponFlip = a.Size() >= 5 && a[4] == "1";   // drawn tip top-left: mirrored (assets.py lean)
			weaponFrame = a.Size() >= 6 ? a[5] : "A";   // B: turned for the hand (bows, assets.py)
		}
		else if (c == "d" && a.Size() >= 2)
		{
			if (a[1].ToInt() == selfId)
			{
				selfId = -1;
			}
			Put(a[1].ToInt(), null);
		}
		else if (c == "shift" && a.Size() >= 3)
		{
			Vector2 by = (a[1].ToDouble(), a[2].ToDouble());
			for (int i = 0; i < gKind.Size(); i++)
			{
				if (gKind[i] != 0)
				{
					gX[i] += by.x;
					gY[i] += by.y;
				}
			}
			Console.PrintfEx(PRINT_HIGH | PRINT_NONOTIFY, "[romtg] shift %.1f %.1f at tic %d", by.x, by.y, level.maptime);
			panX += by.x;
			panY += by.y;
			SetFloorPan();
			// You move with the world at once: your `p` can come a tic later, and for that tic
			// you stood 24 tiles from everything, seeing an empty map (the flicker at some spots
			// in the nexus, where the origin re-centres; Ryan's frame, 2026-11-12).
			// A teleport, not SetOrigin: Doom's renderer keeps its own last camera position and
			// would sweep the view across the 24 tiles for a frame (an empty world mid-way: the
			// flicker, uzdoom.log's shifts line up with it, 2026-11-13). TeleportMove tells it
			// not to (RF_NOINTERPOLATEVIEW).
			mo.TeleportMove(mo.pos + (by.x, by.y, 0), false);
			for (int i = 0; i < pathX.Size(); i++)
			{
				pathX[i] += by.x;
				pathY[i] += by.y;
			}
			gridAt += by;
			lastGoto += by;
			// Everything else in the world moves too, never sliding (a slide across 24 tiles
			// shows for a frame: things flung about, Ryan 2026-11-13): health bars, the spray.
			for (int i = 0; i < bars.Size(); i++)
			{
				if (bars[i] != null)
				{
					bars[i].SetOrigin(bars[i].pos + (by.x, by.y, 0), false);
				}
			}
			for (int i = 0; i < drops.Size(); i++)
			{
				drops[i].SetOrigin(drops[i].pos + (by.x, by.y, 0), false);
			}
			for (int i = 0; i < things.Size(); i++)
			{
				if (things[i] == null)
				{
					continue;
				}
				let w = RomtgWall(things[i]);
				if (w != null)
				{
					w.MoveBy(by);
				}
				else
				{
					things[i].SetOrigin(things[i].pos + (by.x, by.y, 0), false);
				}
			}
		}
		else if (c == "clear")
		{
			selfId = -1;   // its id may go to something else now (KeepSelf would carry that about)
			Console.PrintfEx(PRINT_HIGH | PRINT_NONOTIFY, "[romtg] clear at tic %d", level.maptime);
			for (int i = 0; i < things.Size(); i++)
			{
				if (things[i] != null)
				{
					things[i].Destroy();
				}
			}
			things.Clear();
			thingHp.Clear();
			thingMax.Clear();
			for (int i = 0; i < bars.Size(); i++)
			{
				if (bars[i] != null)
				{
					bars[i].Destroy();
				}
			}
			bars.Clear();
			barIds.Clear();
			farTiles.Clear();
			gKind.Clear(); gColor.Clear(); gX.Clear(); gY.Clear(); gSprite.Clear();
			gAnim.Clear(); gDx.Clear(); gDy.Clear();
			panX = panY = 0;
			SetFloorPan();
			pathT.Clear(); pathX.Clear(); pathY.Clear();
			replaying = false;
			gridCells.Clear();
			groundVersion++;
			fxThing.Clear();
			fxColor.Clear();
			for (int i = 0; i < drops.Size(); i++)
			{
				drops[i].Destroy();
			}
			drops.Clear();
			floatThing.Clear(); floatX.Clear(); floatY.Clear(); floatZ.Clear();
			floatColor.Clear(); floatAt.Clear(); floatText.Clear();
			// A new map: no conveyor under you any more (Ryan, 2026-11-16: R off Sprite World's
			// belt, still carried along in the Nexus). Its next `push` says if there is one.
			walkPush = (0, 0);
		}
	}

	// Slot ID holds `t` from now on; whatever was there goes.
	// Drop every other list's hold on a thing about to go. A dynamic array keeps a destroyed
	// actor's pointer (no null check catches it), and the memory goes to the next actor
	// spawned: a fountain's spray carried on to whatever came next, often a realm portal
	// (Ryan, 2026-11-13).
	void Forget(Actor t)
	{
		for (int i = fxThing.Size() - 1; i >= 0; i--)
		{
			if (fxThing[i] == t)
			{
				fxThing.Delete(i);
				fxColor.Delete(i);
			}
		}
		for (int i = 0; i < floatThing.Size(); i++)
		{
			if (floatThing[i] == t)
			{
				floatThing[i] = null;   // the number stays where it was
			}
		}
		for (int i = farTiles.Size() - 1; i >= 0; i--)
		{
			if (farTiles[i] == t)
			{
				farTiles.Delete(i);
			}
		}
	}

	void Put(int id, Actor t)
	{
		if (id < 0)
		{
			if (t != null) t.Destroy();
			return;
		}
		if (id >= things.Size())
		{
			things.Resize(id + 1);
		}
		if (things[id] != null)
		{
			Forget(things[id]);
			things[id].Destroy();
		}
		things[id] = t;
		if (id < trailTics.Size())
		{
			trailTics[id] = 0;   // a new thing in this slot: no trail until told
		}
		if (id < shotAimed.Size())
		{
			shotAimed[id] = false;
		}
		if (id < animAct.Size())
		{
			animAct[id] = -1;
		}
		if (id < nameText.Size())
		{
			nameText[id] = "";   // nor a name tag
		}
		if (id < healing.Size())
		{
			healing[id] = false;
		}
		if (t != null)
		{
			// Faded for where it is from its first frame: drawn solid until the next fade, it
			// flashed in at the edge of the fog (Ryan, 2026-11-13).
			PlayerInfo p = players[consoleplayer];
			if (p != null && p.mo != null)
			{
				FadeThing(t, p.mo, -1);
			}
		}
		if (id < gKind.Size() && gKind[id] != 0)
		{
			gKind[id] = 0;
			groundVersion++;
		}
		if (id < thingMax.Size())
		{
			thingMax[id] = 0;   // a new thing in this slot: no health bar until told
		}
		if (id < bars.Size() && bars[id] != null)
		{
			bars[id].Destroy();   // PlaceBars forgets its id
			bars[id] = null;
		}
	}
}

// What every piece of the realm has in common: it only shows a RotMG picture.
class RomtgPiece : Actor
{
	Default
	{
		+NOINTERACTION
		+NOBLOCKMAP
		+NOGRAVITY
		+DONTSPLASH
		+NOTONAUTOMAP
		Radius 1;
		Height 1;
	}

	// Sprite SPRITE (a 4-character name from scripts/assets.py), scaled by SCALE.
	static void Dress(Actor t, string sprite, double scale)
	{
		if (t == null)
		{
			return;
		}
		name n = sprite;
		int index = Actor.GetSpriteIndex(n);
		if (index < 0)
		{
			t.Destroy();
			return;
		}
		t.sprite = index;
		t.frame = 0;
		t.scale = (scale, scale);
	}

	States
	{
	Spawn:
		TNT1 A -1;
		Stop;
	}
}

class RomtgFlat : RomtgPiece
{
	Default
	{
		+FLATSPRITE
	}
}

class RomtgBillboard : RomtgPiece
{
}

class RomtgSide : RomtgPiece
{
	Default
	{
		+WALLSPRITE
	}
}

// A RotMG wall: a box of four wall sprites and a flat top, SIZE on each side.
class RomtgWall : RomtgPiece
{
	Array<Actor> parts;
	double boxHalf, boxHeight;   // the box: BOXHALF each way round pos, BOXHEIGHT up from it

	void Build(double size, string side, string top, double scale, double height = 0)
	{
		double half = size / 2;
		if (height <= 0)
		{
			height = size;
		}
		boxHalf = half;
		boxHeight = height;
		for (int i = 0; i < 4; i++)
		{
			// East, north, west and south faces, each facing out.
			double a = i * 90;
			Actor s = Actor.Spawn("RomtgSide", pos + (cos(a) * half, sin(a) * half, height / 2));
			if (s == null) continue;
			s.angle = a;
			RomtgPiece.Dress(s, side, scale);
			if (s != null)
			{
				s.scale.y = scale * height / size;   // the picture stretched to the box's height
				parts.Push(s);
			}
		}
		if (top != "-")
		{
			Actor t = Actor.Spawn("RomtgFlat", pos + (0, 0, height));
			RomtgPiece.Dress(t, top, scale);
			if (t != null) parts.Push(t);
		}
	}

	void MoveBy(Vector2 by)
	{
		SetOrigin(pos + (by.x, by.y, 0), false);
		for (int i = 0; i < parts.Size(); i++)
		{
			if (parts[i] != null)
			{
				parts[i].SetOrigin(parts[i].pos + (by.x, by.y, 0), false);
			}
		}
	}

	override void OnDestroy()
	{
		for (int i = 0; i < parts.Size(); i++)
		{
			if (parts[i] != null)
			{
				parts[i].Destroy();
			}
		}
		parts.Clear();
		Super.OnDestroy();
	}
}

// You: Doom turns and looks, RotMG walks and shoots. No speed of its own, so Doom's movement
// keys only choose a direction (sent as `m`) and the position comes back from RotMG. No Doom
// weapons: the hand is empty and the handler draws your RotMG weapon instead.
class RomtgPlayer : PlayerPawn
{
	Default
	{
		Speed 0;
		Health 100;
		Radius 16;
		Height 56;
		Mass 100;
		Player.DisplayName "Realm";
		Player.ViewBob 0;
		Player.JumpZ 0;
		Player.StartItem "RomtgHand";
		Player.WeaponSlot 1, "RomtgHand";
	}

	States
	{
	Spawn:
		TNT1 A -1;
		Loop;
	}
}

// An empty Doom weapon: fire only tells RotMG (RomtgHandler.SendFire), nothing happens in Doom.
class RomtgHand : Weapon
{
	Default
	{
		+WEAPON.NOAUTOFIRE
		+WEAPON.NOALERT
		+WEAPON.CHEATNOTWEAPON
		Weapon.SelectionOrder 1;
		Weapon.BobStyle "Smooth";
	}

	States
	{
	Ready:
		TNT1 A 1 A_WeaponReady(WRF_NOFIRE);
		Loop;
	Deselect:
		TNT1 A 1 A_Lower;
		Loop;
	Select:
		TNT1 A 1 A_Raise;
		Loop;
	Fire:
		TNT1 A 1;
		Goto Ready;
	}
}

// A drop of fountain spray: a dot of the fountain's colour flying up and falling back, for a
// set number of tics. An actor, so it can be moved and removed with the rest of the world.
class RomtgDrop : Actor
{
	Vector3 v;
	double g;
	int life, lifetime;
	double size;
	bool shrink;                    // shrinks to nothing over its life (a spark)

	Default
	{
		+NOINTERACTION
		+NOBLOCKMAP
		+NOGRAVITY
		+DONTSPLASH
		+NOTONAUTOMAP
		+BRIGHT
		RenderStyle "Stencil";
	}

	void Start(int rgb, double size, int tics, Vector3 vel, double gravity)
	{
		v = vel;
		g = gravity;
		life = tics;
		lifetime = tics;
		self.size = size;
		RomtgPiece.Dress(self, "ZWHT", size);
		SetShade(Color(255, (rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255));
	}

	// Never destroys itself: the handler does (Fountains), so its list never holds a dead one.
	override void Tick()
	{
		if (life <= 0)
		{
			return;
		}
		life--;
		SetOrigin(pos + v, true);
		v.z -= g;
		if (shrink && lifetime > 0)
		{
			double s = size * life / lifetime;
			scale = (s, s);
		}
	}

	States
	{
	Spawn:
		TNT1 A -1;
		Stop;
	}
}
