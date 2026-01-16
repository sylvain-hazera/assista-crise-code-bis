import { ComponentFixture, TestBed } from '@angular/core/testing';

import { DeclareCrisisFormComponent } from './declare-crisis-form.component';

describe('DeclareCrisisFormComponent', () => {
  let component: DeclareCrisisFormComponent;
  let fixture: ComponentFixture<DeclareCrisisFormComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DeclareCrisisFormComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(DeclareCrisisFormComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
