// 时间工具：后端统一存储 UTC（naive），前端展示时转换本地时区
// dayjs.utc() 对无时区字符串按 UTC 解析（兼容历史数据），.local() 转浏览器时区
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import 'dayjs/locale/zh-cn'

dayjs.extend(utc)
dayjs.locale('zh-cn')

export function fmtTime(v: string): string {
  return dayjs.utc(v).local().format('YYYY-MM-DD HH:mm')
}

export function fmtTimeFull(v: string): string {
  return dayjs.utc(v).local().format('YYYY-MM-DD HH:mm:ss')
}