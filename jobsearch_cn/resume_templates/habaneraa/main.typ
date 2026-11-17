// 本项目自己写的入口（不是上游文件）：内容从 resume.json 读，间距和字体从 --input 读。
// 数据不拼进 Typst 标记，内容里的 # * = 都按原样显示。
#import "lib.typ": setup-styles

#let data = json("resume.json")
#let (resume-header, resume-entry) = setup-styles(
  sans-serif-font: (sys.inputs.sans,),
  serif-font: (sys.inputs.serif,),
  alt-font: (sys.inputs.sans,),
  element-spaciness: float(sys.inputs.spaciness),
)
// 求职意向按" · "分成几项：20 字以内的一项放进 box，不在中间折行（"2026.11.15 起可到岗"不拆成两行）；
// 不到半行，所以不会撑出版心。更长的一项照常折行。点前面用不换行空格，点留在上一行末尾，不落到行首。
// 整行放进一个占满版心的 box，里面不两端对齐：折行时上一行不会被拉开字距。
#let keep-together(line) = box(width: 100%)[
  #set par(justify: false)
  #line.split(" · ").map(part => if part.clusters().len() <= 20 { box(part) } else { part }).join("\u{a0}· ")
]
#show: resume-header.with(
  author: data.name,
  profile-image: if sys.inputs.at("photo", default: "false") == "true" {
    let photo = json("photo.json")
    image("portrait.png", width: photo.width_emu / 36000 * 1mm, height: photo.height_emu / 36000 * 1mm, fit: "contain")
  } else { none },
  basic-info: ([#data.contact #linebreak() #keep-together(data.intent)],),
)

#for s in data.sections [
  = #s.title
  #if "text" in s [
    #s.text
  ]
  #for e in s.at("entries", default: ()) [
    #resume-entry(title: e.left, subtitle: e.middle, date: e.right)[
      #for b in e.bullets [
        - #b
      ]
    ]
  ]
  #for l in s.at("lines", default: ()) [
    - #if l.label != "" [*#l.label*：]#l.rest
  ]
]
