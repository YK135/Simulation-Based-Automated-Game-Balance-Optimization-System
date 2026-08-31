let state = {
    player: null,
    inBattle: false,
    battleState: null,
    battleMessages: [],   // 도감 "발견" 판정용 — 현재 전투의 누적 메시지 (MapActions.js가 전투 시작 시 리셋)
    exploreTurn: 0,

    // 비동기 락 (race condition 방지)
    exploring: false,
    battleProcessing: false,

    // 시작 플로우 (3단계 모달)
    selectedJob: '전사',
    isEmailAuth: false,
    userEmail: null,
    creatingNewGame: false,
};

// ★ 전역 명시화 — CharSprite.js 등 외부 모듈이 window.state로 안전 접근
window.state = state;

// ═══════════════════════════════════════════════════════════
// 이모지 폴백 (이미지 없을 때)
// ═══════════════════════════════════════════════════════════
const JOB_ICONS = { '전사':'⚔', '마법사':'⚡', '탱커':'🛡', '도적':'🗡' };

// ─────────────────────────────────────────────────────────
// 아이템 아이콘 매핑 (ai/battle/Items.py ITEM_META 영문 키 기준)
//   값 형식: { icon: 이모지폴백, img: 이미지경로 }
//   renderIconWithFallback(Utils.js)가 img 우선, 실패/없으면 icon 표시
// ─────────────────────────────────────────────────────────
const ITEM_ICONS = {
    HP_S_potion: { icon: '🧪', img: '/img/icons/items/hp_potion.png' },
    HP_M_potion: { icon: '🧪', img: '/img/icons/items/hp_potion.png' },
    HP_L_potion: { icon: '🧪', img: '/img/icons/items/hp_potion.png' },
    MP_S_potion: { icon: '🔵', img: '/img/icons/items/mp_potion.png' },
    MP_M_potion: { icon: '🔵', img: '/img/icons/items/mp_potion.png' },
    MP_L_potion: { icon: '🔵', img: '/img/icons/items/mp_potion.png' },
    bomb:              { icon: '💣', img: '/img/icons/items/bomb.png' },
    web_bomb:          { icon: '🕸', img: '/img/icons/items/web_bomb.png' },
    fire_vial:         { icon: '🔥', img: '/img/icons/items/fire_vial.png' },
    ice_vial:          { icon: '❄', img: '/img/icons/items/ice_vial.png' },
    lightning_crystal: { icon: '⚡', img: '/img/icons/items/lightning_crystal.png' },
    focus_drug:        { icon: '🎯', img: '/img/icons/items/focus_drug.png' },
    haste_drug:        { icon: '💨', img: '/img/icons/items/haste_drug.png' },
};

// ─────────────────────────────────────────────────────────
// 아이템 표시명 (화면 표시 전용 — API 전송은 항상 영문 id 사용)
// ─────────────────────────────────────────────────────────
const ITEM_LABELS = {
    HP_S_potion: 'HP 소형 포션',
    HP_M_potion: 'HP 중형 포션',
    HP_L_potion: 'HP 대형 포션',
    MP_S_potion: 'MP 소형 포션',
    MP_M_potion: 'MP 중형 포션',
    MP_L_potion: 'MP 대형 포션',
    bomb:              '폭탄',
    web_bomb:          '거미줄 폭탄',
    fire_vial:         '화염 병',
    ice_vial:          '냉기 병',
    lightning_crystal: '전격 수정',
    focus_drug:        '집중 물약',
    haste_drug:        '신속 물약',
};

// id → 표시명 (없으면 id 그대로). 화면 표시에만 사용.
function itemLabel(id) {
    return (typeof ITEM_LABELS !== 'undefined' && ITEM_LABELS[id]) || id;
}

// ─────────────────────────────────────────────────────────
// 아이템 설명 (툴팁용 — 좌측 패널/전투 ITEMS 메뉴/상점/보상 팝업 공용)
// ─────────────────────────────────────────────────────────
const ITEM_DESCRIPTIONS = {
    HP_S_potion: 'HP를 소량 회복한다',
    HP_M_potion: 'HP를 중간량 회복한다',
    HP_L_potion: 'HP를 대량 회복한다',
    MP_S_potion: 'MP를 소량 회복한다',
    MP_M_potion: 'MP를 중간량 회복한다',
    MP_L_potion: 'MP를 대량 회복한다',
    bomb:              '적 전체에게 피해',
    web_bomb:          '적 전체 피해 + 속도 감소',
    fire_vial:         '단일 적에게 화염 부착',
    ice_vial:          '단일 적에게 빙결 부착',
    lightning_crystal: '단일 적에게 번개 부착',
    focus_drug:        '다음 스킬 피해 증가',
    haste_drug:        '다음 행동 후 ATB 추가 획득',
};

// id → 설명 (없으면 빈 문자열). 툴팁 표시 전용.
function itemDesc(id) {
    return (typeof ITEM_DESCRIPTIONS !== 'undefined' && ITEM_DESCRIPTIONS[id]) || '';
}



// ─────────────────────────────────────────────────────────
// 원소 아이콘 (현재는 매핑만 — 원소 부착은 이름 색상으로 표시, 아이콘 미사용)
// ─────────────────────────────────────────────────────────
const ELEMENT_ICONS = {
    fire:      { icon: '🔥', img: '/img/icons/elements/fire.png' },
    ice:       { icon: '❄', img: '/img/icons/elements/ice.png' },
    lightning: { icon: '⚡', img: '/img/icons/elements/lightning.png' },
};

// ─────────────────────────────────────────────────────────
// 상태이상 아이콘 (이름 옆 표시). ignite/frostbite/paralyze + buff/debuff
// ─────────────────────────────────────────────────────────
const STATUS_ICONS = {
    ignite:    { icon: '🔥', img: '/img/icons/status/ignite.png' },
    frostbite: { icon: '❄', img: '/img/icons/status/frostbite.png' },
    paralyze:  { icon: '⚡', img: '/img/icons/status/paralyze.png' },
    buff:      { icon: '↑', img: '/img/icons/status/buff_up.png' },
    debuff:    { icon: '↓', img: '/img/icons/status/debuff_down.png' },
};


const ENEMY_ICONS = {
    '고블린':'👺', '박쥐':'🦇', '슬라임':'🟢',
    '골렘':'🗿', '유령':'👻', '암살자':'🥷',
    '사제':'⚕',
    '중간 보스':'👹', '최종 보스':'🐉',
};

// ═══════════════════════════════════════════════════════════
// 직업 데이터 매핑 (모달 3 직업 선택용)
// ═══════════════════════════════════════════════════════════
const JOB_DATA = {
    '전사': {
        name: 'WARRIOR',
        icon: '⚔',
        tags: ['균형형', '물리'],
        description:
            '높은 HP와 안정적인 물리 데미지를 갖춘 균형형 전사. ' +
            '초보자에게 가장 적합하며, 모든 상황에서 안정적인 성능을 발휘한다.',
        passive: '【패시브】 공격 3회마다 최대 HP 10% 자동 회복',
    },
    '마법사': {
        name: 'MAGE',
        icon: '✦',
        tags: ['마법', '원소 반응'],
        description:
            '원소를 조합해 반응을 일으키는 원소술사. ' +
            '융해·과부하 반응으로 폭발적인 추가 피해를 노린다.',
        passive: '【패시브】 융해/과부하 반응 피해 +5% · 원소 반응 시 MP 8% 회복',
    },
    '탱커': {
        name: 'TANKER',
        icon: '▣',
        tags: ['방어형', '회복'],
        description:
            '높은 방어력과 피격 시 자원 회복. ' +
            '오래 버티며 적의 공격을 견뎌내는 인내형 직업.',
        passive: '【패시브】 물리 피격 시 MP 회복 / 마법 피격 시 HP 회복 (각 10%)',
    },
    '도적': {
        name: 'ROGUE',
        icon: '✧',
        tags: ['속도형', '도박수'],
        description:
            '주사위 운명에 몸을 맡기는 속도형 검사. ' +
            '높은 SPD로 회피하고, 회피 순간 즉시 반격한다.',
        passive: '【패시브】 공격 시 주사위(×0.75~×1.25, 6=치명타+출혈+ATB) · 회피 시 반격',
    },
};

// ═══════════════════════════════════════════════════════════
// 상태별 이미지 매핑 (실제 존재 파일만)
// ───────────────────────────────────────────────────────────
// 등록 안 된 직업/몬스터는 getCharImage()가 null 반환 → 이모지 폴백.
// 새 이미지 추가 시 여기에 등록만 하면 자동 사용됨.
//
// 파일 구조 (실제 존재):
//   static/img/face/warrior_face_A.png   (idle 얼굴)
//   static/img/face/warrior_face_B.png   (hurt 얼굴)
//   static/img/face/warrior_face_C.png   (happy 얼굴)
//   static/img/battle/warrior_A.png      (배틀 전사)
// ═══════════════════════════════════════════════════════════

// ─────────────────────────────────────────────────────────
// 스프라이트 값 형식 (CharSprite.js가 둘 다 지원):
//   1) 문자열 (정지 PNG, 현재 방식):
//        idle: '/img/sprites/player/warrior_A.png'
//   2) 객체 (sprite sheet 애니메이션, 에셋 준비 후 교체):
//        idle: { src:'/img/sprites/player/warrior_A.png', type:'sheet',
//                frames:4, fps:6, loop:true, frameWidth:128, frameHeight:128 }
//        attack: { ..., loop:false }   // 1회 재생 후 idle 복귀
//   값이 없으면 이모지 폴백. 문자열↔객체 혼용 가능 (상태별 개별 전환 OK).
// ─────────────────────────────────────────────────────────
const CHAR_IMAGES = {

    // 좌측 플레이어 패널 — 직업별 초상화 (portraits/)
    //   setCharState('player_panel','idle')이 이 경로를 player-portrait.src에 세팅.
    //   이미지 없으면 onerror로 player-icon(이모지) 폴백 (CharSprite.js 처리).
    player_panel: {
        '전사':   { idle: '/img/portraits/warrior.png' },
        '마법사': { idle: '/img/portraits/mage.png' },
        '탱커':   { idle: '/img/portraits/tanker.png' },
        '도적':   { idle: '/img/portraits/rogue.png' },
    },

    // 배틀필드 플레이어 — 전신 (idle/attack/skill/hurt/dead)
    // 전투 필드 — 직업별 스프라이트 (sprites/player/, 상태 A~E)
    //   A=idle B=attack C=skill D=hurt E=dead
    //   파일 없으면 getCharImage가 idle→null 폴백 → 이모지 표시 (CharSprite.js)
    player_battle: {
        '전사': {
            // ★ sprite sheet 더미 테스트: idle만 객체 메타 (나머지는 문자열 유지)
            //   warrior_A.png를 가로 4프레임(512x128) 시트로 넣으면 idle 반복 재생.
            //   시트가 아니라 단일 PNG여도 frames=4라 4등분 시도 → 더미 시트 권장.
            idle:   { src: '/img/sprites/player/warrior_A.png', type: 'sheet',
                      frames: 4, fps: 6, loop: true, frameWidth: 128, frameHeight: 128 },
            attack: '/img/sprites/player/warrior_B.png',
            skill:  '/img/sprites/player/warrior_C.png',
            hurt:   '/img/sprites/player/warrior_D.png',
            dead:   '/img/sprites/player/warrior_E.png',
        },
        '마법사': {
            // ★ "Free/Characters/1" 에셋 적용 (walk→idle 대용, skill 프레임은 없어서 보류)
            idle:   { src: '/img/sprites/player/mage_A.png', type: 'sheet', frames: 8, fps: 8,  loop: true },
            attack: { src: '/img/sprites/player/mage_B.png', type: 'sheet', frames: 8, fps: 14, loop: false },
            skill:  '/img/sprites/player/mage_C.png',
            hurt:   { src: '/img/sprites/player/mage_D.png', type: 'sheet', frames: 8, fps: 14, loop: false },
            dead:   { src: '/img/sprites/player/mage_E.png', type: 'sheet', frames: 8, fps: 10, loop: false },
        },
        '탱커': {
            idle:   '/img/sprites/player/tanker_A.png',
            attack: '/img/sprites/player/tanker_B.png',
            skill:  '/img/sprites/player/tanker_C.png',
            hurt:   '/img/sprites/player/tanker_D.png',
            dead:   '/img/sprites/player/tanker_E.png',
        },
        '도적': {
            idle:   '/img/sprites/player/rogue_A.png',
            attack: '/img/sprites/player/rogue_B.png',
            skill:  '/img/sprites/player/rogue_C.png',
            hurt:   '/img/sprites/player/rogue_D.png',
            dead:   '/img/sprites/player/rogue_E.png',
        },
    },

    // 배틀필드 몬스터 — 모두 이미지 없음 → 이모지 폴백
    // 전투 필드 — 몬스터 스프라이트 (sprites/monsters/, 상태 A~E)
    //   키는 Enemy_Class.py의 실제 unit.name과 정확히 일치해야 함 (공백 포함)
    //   B/C 없으면 idle 폴백 OK (몬스터는 A/D/E만 있어도 됨)
    enemy_battle: {
        '고블린': {
            idle:   '/img/sprites/monsters/goblin_A.png',
            attack: '/img/sprites/monsters/goblin_B.png',
            skill:  '/img/sprites/monsters/goblin_C.png',
            hurt:   '/img/sprites/monsters/goblin_D.png',
            dead:   '/img/sprites/monsters/goblin_E.png',
        },
        // DarkFantasyEnemies_FREE 팩 적용 (VFX 포함 버전 — 타격/사망 이펙트가
        // 프레임에 이미 그려져 있어 별도 이펙트 레이어 없이도 효과가 보임).
        // 프레임 수는 각 시트 실제 픽셀폭 ÷ 64(프레임 높이)로 확인한 값.
        '박쥐': {
            idle:   { src: '/img/sprites/monsters/bat_A.png', type: 'sheet',
                      frames: 9,  fps: 8,  loop: true },   // Bat-IdleFly (날갯짓)
            attack: { src: '/img/sprites/monsters/bat_B.png', type: 'sheet',
                      frames: 8,  fps: 14, loop: false },  // Bat-Attack1
            skill:  { src: '/img/sprites/monsters/bat_C.png', type: 'sheet',
                      frames: 11, fps: 12, loop: false },  // Bat-Attack2 (스킬용으로 구분)
            hurt:   { src: '/img/sprites/monsters/bat_D.png', type: 'sheet',
                      frames: 5,  fps: 14, loop: false },  // Bat-Hurt
            dead:   { src: '/img/sprites/monsters/bat_E.png', type: 'sheet',
                      frames: 12, fps: 10, loop: false },  // Bat-Die
        },
        '슬라임': {
            idle:   '/img/sprites/monsters/slime_A.png',
            attack: '/img/sprites/monsters/slime_B.png',
            skill:  '/img/sprites/monsters/slime_C.png',
            hurt:   '/img/sprites/monsters/slime_D.png',
            dead:   '/img/sprites/monsters/slime_E.png',
        },
        '화염 슬라임': {
            idle:   '/img/sprites/monsters/fire_slime_A.png',
            attack: '/img/sprites/monsters/fire_slime_B.png',
            skill:  '/img/sprites/monsters/fire_slime_C.png',
            hurt:   '/img/sprites/monsters/fire_slime_D.png',
            dead:   '/img/sprites/monsters/fire_slime_E.png',
        },
        '빙결 슬라임': {
            idle:   '/img/sprites/monsters/ice_slime_A.png',
            attack: '/img/sprites/monsters/ice_slime_B.png',
            skill:  '/img/sprites/monsters/ice_slime_C.png',
            hurt:   '/img/sprites/monsters/ice_slime_D.png',
            dead:   '/img/sprites/monsters/ice_slime_E.png',
        },
        '번개 슬라임': {
            idle:   '/img/sprites/monsters/lightning_slime_A.png',
            attack: '/img/sprites/monsters/lightning_slime_B.png',
            skill:  '/img/sprites/monsters/lightning_slime_C.png',
            hurt:   '/img/sprites/monsters/lightning_slime_D.png',
            dead:   '/img/sprites/monsters/lightning_slime_E.png',
        },
        '골렘': {
            idle:   '/img/sprites/monsters/golem_A.png',
            attack: '/img/sprites/monsters/golem_B.png',
            skill:  '/img/sprites/monsters/golem_C.png',
            hurt:   '/img/sprites/monsters/golem_D.png',
            dead:   '/img/sprites/monsters/golem_E.png',
        },
        '유령': {
            idle:   '/img/sprites/monsters/ghost_A.png',
            attack: '/img/sprites/monsters/ghost_B.png',
            skill:  '/img/sprites/monsters/ghost_C.png',
            hurt:   '/img/sprites/monsters/ghost_D.png',
            dead:   '/img/sprites/monsters/ghost_E.png',
        },
        '암살자': {
            idle:   '/img/sprites/monsters/assassin_A.png',
            attack: '/img/sprites/monsters/assassin_B.png',
            skill:  '/img/sprites/monsters/assassin_C.png',
            hurt:   '/img/sprites/monsters/assassin_D.png',
            dead:   '/img/sprites/monsters/assassin_E.png',
        },
        '사제': {
            idle:   '/img/sprites/monsters/priest_A.png',
            attack: '/img/sprites/monsters/priest_B.png',
            skill:  '/img/sprites/monsters/priest_C.png',
            hurt:   '/img/sprites/monsters/priest_D.png',
            dead:   '/img/sprites/monsters/priest_E.png',
        },
        '중간 보스': {
            idle:   '/img/sprites/monsters/midboss_A.png',
            attack: '/img/sprites/monsters/midboss_B.png',
            skill:  '/img/sprites/monsters/midboss_C.png',
            hurt:   '/img/sprites/monsters/midboss_D.png',
            dead:   '/img/sprites/monsters/midboss_E.png',
        },
        '최종 보스': {
            idle:   '/img/sprites/monsters/finalboss_A.png',
            attack: '/img/sprites/monsters/finalboss_B.png',
            skill:  '/img/sprites/monsters/finalboss_C.png',
            hurt:   '/img/sprites/monsters/finalboss_D.png',
            dead:   '/img/sprites/monsters/finalboss_E.png',
        },
    },
};


// ═══════════════════════════════════════════════════════════
// 헬퍼: 캐릭터 이미지 경로 조회
// ───────────────────────────────────────────────────────────
// section:   'player_panel' | 'player_battle' | 'enemy_battle'
// name:      직업명 or 몬스터명 (한글)
// stateName: 'idle' | 'hurt' | 'attack' | 'skill' | 'dead' | 'happy'
//
// 반환: 이미지 경로 (string) 또는 null (이미지 없음 → 이모지 폴백)
// 폴백: 요청 상태 없으면 idle → 그것도 없으면 null
// ═══════════════════════════════════════════════════════════
function getCharImage(section, name, stateName) {
    const sectionMap = CHAR_IMAGES[section];
    if (!sectionMap) return null;
    const charMap = sectionMap[name];
    if (!charMap) return null;
    return charMap[stateName] || charMap['idle'] || null;
}