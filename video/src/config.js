// Settings and editable content shared by the segments.

export const VIDEO = { width: 1920, height: 1080, fps: 60 };

export const REPO = {
  owner: 'destire-mio',
  name: 'sts-ironclad-agent',
  url: 'github.com/destire-mio/sts-ironclad-agent',
  license: 'MIT',
  related: [
    { name: 'sts-ironclad-simulator', note: '纯模拟器包' },
    { name: 'sts-search-advisor', note: '战斗回合顾问' },
  ],
};

// Evaluation numbers for segment 11. `null` renders a placeholder ("XX.X%").
// Fill these in (percentages as numbers, e.g. 50.1) and re-render segment 11.
export const EVAL = {
  hero: { label: '真实游戏 · 击败心脏', value: null, lo: null, hi: null, games: null },
  rows: [
    { label: '模拟器', who: '老师', value: null, games: null, color: 'gold' },
    { label: '模拟器', who: '学生', value: null, games: null, color: 'cyan' },
    { label: '真实游戏', who: '学生', value: null, games: null, color: 'red' },
  ],
  // Death rate among games that reach each stage.
  stages: [
    { label: '第一幕路上', value: null },
    { label: '第一幕 Boss', value: null },
    { label: '第二幕路上', value: null },
    { label: '第二幕 Boss', value: null },
    { label: '第三幕路上', value: null },
    { label: '第三幕 Boss', value: null },
    { label: '盾与矛', value: null },
    { label: '心脏', value: null },
  ],
  rules: ['固定种子', '不换种子', '不重试', '故障单列'],
};
