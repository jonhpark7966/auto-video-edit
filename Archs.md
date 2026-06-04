

## components
- chalna <- eval set 으로 segment 자르기 바꾸기.
- auto-video-edit
- eogum
- (TODO) tts


## User Needs Assumption

- podcast & lecture & interview (정보전달 컨텐츠)
	- 나름 전문가로서 설명하고자 하는 사람
	- 아직 유투브를 개설하지 않은 사람
- (후보) 게임 & 스포츠 하이라이트

- Raw Video -> edited Video -> human editor (eogum crew... STUDIO가 될 수도 있다)
- Storage (ex. google drive), video editor (web based) + timing editing
- Multicam auto + speaker dialization...
- Editing - style 1 (sudoremove), style 2 (EEGIRIT), style 3 (...), custom style (...)

## Future work
- video editor features - 효과? 포인트 자막, 효과음, 트랜지션, ...
- VLM - screen based editing
- 인간 편집자보다 잘한다, 뭘 하면 인간보다 더 잘 할 수 있을까?
	- 추가 정보 달아주기 & 인포그래픽 만들어주기
	- 촬영이 불가능한 씬을 삽입
	- ...??


## Architectures - auto-video-edit

- edit segment (words, word (start, end time))
- decision (in/out, reason, ...)
- skill (decision making) - prompt

- video -> segments + decision (AI version / Human Version)