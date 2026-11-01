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
#show: resume-header.with(
  author: data.name,
  basic-info: ([#data.contact #linebreak() #data.intent],),
)

#for s in data.sections [
  = #s.title
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
