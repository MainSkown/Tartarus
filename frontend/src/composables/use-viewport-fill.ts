import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

/**
 * The height, in pixels, between the top of `element` and the bottom of the viewport, so a panel
 * can fill the screen under whatever header sits above it without the page scrolling. It is
 * measured, not assumed, and re-measured when the window or the content above it changes size.
 */
export function useViewportFill(element: Ref<HTMLElement | undefined>, bottomGap = 0): { height: Ref<number> } {
  const height = ref(0)
  let observer: ResizeObserver | undefined

  function measure(): void {
    if (!element.value) return
    const top = element.value.getBoundingClientRect().top + window.scrollY
    height.value = Math.floor(window.innerHeight - top - bottomGap)
  }

  onMounted(() => {
    measure()
    window.addEventListener('resize', measure)
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(measure)
      observer.observe(document.body)
    }
  })
  onBeforeUnmount(() => {
    window.removeEventListener('resize', measure)
    observer?.disconnect()
  })

  return { height }
}
