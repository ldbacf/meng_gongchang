import { ref, watch, nextTick } from 'vue'
import type { Ref } from 'vue'

/**
 * 消息区滚动跟随。
 *
 * 三个语义必须分清，混在一起就会出 bug：
 *   1. **跟随**（stick）：只有用户本来就在底部时，新内容才把他带到新底部
 *   2. **不打扰**：用户主动往上翻看历史时，不能被拽回来
 *   3. **主动归位**：发新消息 / 切会话时，无论之前在哪都落到底部
 *
 * 历史坑：原来用 `lastElementChild.scrollIntoView()`，消息区外层套了 760px 居中容器后，
 * `lastElementChild` 就是**整块容器**，`scrollIntoView` 会把它顶部对齐视口顶部，
 * 于是每次发消息都跳回开头。必须直接改 `scrollTop`。
 *
 * @param container  滚动容器（`overflow-y-auto` 那一层）
 * @param trigger    「内容变了」的信号：watch 它来决定要不要跟随
 */
export function useStickToBottom(
  container: Ref<HTMLElement | null>,
  trigger: () => unknown,
) {
  /** 距底部多少像素以内仍算「贴着底部」 */
  const STICK_THRESHOLD = 80

  const stickToBottom = ref(true)

  function onScroll() {
    const el = container.value
    if (!el) return
    stickToBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD
  }

  /**
   * 滚到底部。
   *
   * 流式期间必须用 `behavior: 'auto'`：平滑滚动途中会产生一串
   * 「还没到底」的中间 scroll 事件，被 onScroll 判成「用户上翻了」，
   * 下一次更新就不再跟随，滚动会半路停住。
   */
  function scrollToBottom(smooth = true) {
    const el = container.value
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  }

  /** 无条件落到底部（发消息、切会话时用） */
  async function forceBottom(smooth = false) {
    stickToBottom.value = true
    await nextTick()
    scrollToBottom(smooth)
  }

  watch(trigger, async () => {
    await nextTick()
    // 用户正在往上翻：不要打扰
    if (!stickToBottom.value) return
    scrollToBottom(true)
  })

  return { stickToBottom, onScroll, scrollToBottom, forceBottom }
}
