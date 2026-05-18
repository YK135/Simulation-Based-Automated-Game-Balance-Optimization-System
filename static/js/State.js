let state = {
    player: null,
    inBattle: false,
    battleState: null,
    aiLevel: 'normal',
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
        tags: ['마법', '효율형'],
        description:
            '강력한 마법 공격과 효율적인 MP 관리. ' +
            '슬라임 같은 마법 약점 적에게 극대화된 데미지를 입힐 수 있다.',
        passive: '【패시브】 모든 스킬 MP 비용 30% 영구 감소',
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
        tags: ['속도형', '치명타'],
        description:
            '빠른 행동력과 치명타 특화. ' +
            '높은 SPD로 선공을 잡고 크리티컬로 단숨에 적을 무력화한다.',
        passive: '【패시브】 치명타 발생 시 70% 확률로 방어력 50% 무시',
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

const CHAR_IMAGES = {

    // 좌측 플레이어 패널 — 얼굴 (idle/hurt/happy)
    player_panel: {
        '전사': {
            idle:  '/img/face/warrior_face_A.png',
            happy:  '/img/face/warrior_face_B.png',
            hurt: '/img/face/warrior_face_C.png',
        },
        // 마법사, 탱커, 도적은 이미지 없음 → 이모지 폴백
    },

    // 배틀필드 플레이어 — 전신 (idle/attack/skill/hurt/dead)
    player_battle: {
        '전사': {
            // 전사 배틀 이미지는 1종(A)뿐 — 모든 상태에 같은 이미지 사용
            // 추후 상태별 이미지 추가 시 여기 경로만 교체
            idle:   '/img/battle/warrior_A.png',
            attack: '/img/battle/warrior_A.png',
            skill:  '/img/battle/warrior_A.png',
            hurt:   '/img/battle/warrior_A.png',
            dead:   '/img/battle/warrior_A.png',
        },
        // 마법사, 탱커, 도적은 이미지 없음 → 이모지 폴백
    },

    // 배틀필드 몬스터 — 모두 이미지 없음 → 이모지 폴백
    enemy_battle: {
        // 추후 몬스터 이미지 추가 시 여기에 등록:
        // '고블린': { idle: '/img/enemy/goblin_idle.png', ... },
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
